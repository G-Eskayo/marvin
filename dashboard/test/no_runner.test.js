import { describe, it, expect, vi } from 'vitest'
import {
  isNoRunnerAnnotation,
  isNoRunnerCheck,
  runIdFromDetailsUrl,
  fetchCommitCheckRuns,
  fetchCheckAnnotations,
  classifyFailingChecks
} from '../webhook-server/no_runner.js'

describe('isNoRunnerAnnotation', () => {
  it('recognizes skipped annotations', () => {
    expect(isNoRunnerAnnotation({ title: 'Skipped', message: 'This check was skipped' })).toBe(true)
    expect(isNoRunnerAnnotation({ message: 'Platform not supported' })).toBe(true)
    expect(isNoRunnerAnnotation({ title: 'NOT RUN' })).toBe(true)
  })

  it('recognizes no-runner message patterns', () => {
    expect(isNoRunnerAnnotation({ message: 'Platform not supported' })).toBe(true)
    expect(isNoRunnerAnnotation({ message: 'No runner available' })).toBe(true)
    expect(isNoRunnerAnnotation({ title: 'Unsupported platform' })).toBe(true)
  })

  it('rejects normal annotations', () => {
    expect(isNoRunnerAnnotation({ title: 'Failed', message: 'Test failed' })).toBe(false)
    expect(isNoRunnerAnnotation({ title: 'Success', message: 'All passed' })).toBe(false)
    expect(isNoRunnerAnnotation(null)).toBe(false)
    expect(isNoRunnerAnnotation({})).toBe(false)
  })
})

describe('isNoRunnerCheck', () => {
  it('recognizes checks with SKIPPED conclusion', () => {
    expect(isNoRunnerCheck({ conclusion: 'SKIPPED' })).toBe(true)
    expect(isNoRunnerCheck({ conclusion: 'skipped' })).toBe(true)
  })

  it('recognizes checks with NEUTRAL or STALE conclusion', () => {
    expect(isNoRunnerCheck({ conclusion: 'NEUTRAL' })).toBe(true)
    expect(isNoRunnerCheck({ conclusion: 'STALE' })).toBe(true)
  })

  it('recognizes checks marked skipped in summary or title', () => {
    expect(isNoRunnerCheck({ summary: 'This check was skipped' })).toBe(true)
    expect(isNoRunnerCheck({ title: 'Not run' })).toBe(true)
    expect(isNoRunnerCheck({ summary: 'Platform not supported, check not run' })).toBe(true)
  })

  it('rejects failed or successful checks', () => {
    expect(isNoRunnerCheck({ conclusion: 'FAILURE' })).toBe(false)
    expect(isNoRunnerCheck({ conclusion: 'SUCCESS' })).toBe(false)
    expect(isNoRunnerCheck({ summary: 'All tests passed' })).toBe(false)
    expect(isNoRunnerCheck(null)).toBe(false)
    expect(isNoRunnerCheck({})).toBe(false)
  })
})

describe('runIdFromDetailsUrl', () => {
  it('extracts run ID from GitHub Actions URL', () => {
    expect(runIdFromDetailsUrl('https://github.com/G-Eskayo/marvin/actions/runs/12345')).toBe('12345')
    expect(runIdFromDetailsUrl('https://github.com/G-Eskayo/marvin/actions/runs/999/attempts/2')).toBe('999')
  })

  it('handles URLs with query parameters', () => {
    expect(runIdFromDetailsUrl('https://github.com/G-Eskayo/marvin/actions/runs/12345?check_suite_id=1')).toBe('12345')
  })

  it('rejects invalid URLs', () => {
    expect(runIdFromDetailsUrl('https://github.com/G-Eskayo/marvin')).toBe(null)
    expect(runIdFromDetailsUrl('not a url')).toBe(null)
    expect(runIdFromDetailsUrl(null)).toBe(null)
    expect(runIdFromDetailsUrl('')).toBe(null)
  })
})

describe('fetchCommitCheckRuns', () => {
  it('calls gh api with correct arguments', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '{"id":"1","name":"test","status":"COMPLETED","conclusion":"SUCCESS"}' })
    const result = await fetchCommitCheckRuns({ repo: 'org/repo', sha: 'a'.repeat(40), exec })
    expect(exec).toHaveBeenCalledWith('gh', expect.arrayContaining(['api', 'repos/org/repo/commits/' + 'a'.repeat(40) + '/check-runs']))
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('1')
  })

  it('handles multiple runs in output', async () => {
    const exec = vi.fn().mockResolvedValue({
      stdout: '{"id":"1","name":"test1"}\n{"id":"2","name":"test2"}'
    })
    const result = await fetchCommitCheckRuns({ repo: 'org/repo', sha: 'b'.repeat(40), exec })
    expect(result).toHaveLength(2)
  })

  it('handles empty output', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '' })
    const result = await fetchCommitCheckRuns({ repo: 'org/repo', sha: 'c'.repeat(40), exec })
    expect(result).toHaveLength(0)
  })

  it('returns empty array on error', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('API error'))
    const result = await fetchCommitCheckRuns({ repo: 'org/repo', sha: 'd'.repeat(40), exec })
    expect(result).toEqual([])
  })

  it('validates SHA format', async () => {
    const exec = vi.fn()
    expect(await fetchCommitCheckRuns({ repo: 'org/repo', sha: 'not-a-sha', exec })).toEqual([])
    expect(exec).not.toHaveBeenCalled()
  })

  it('handles missing arguments gracefully', async () => {
    const result1 = await fetchCommitCheckRuns({})
    const result2 = await fetchCommitCheckRuns({ repo: 'org/repo', sha: 'a'.repeat(40) })
    expect(result1).toEqual([])
    expect(result2).toEqual([])
  })
})

describe('fetchCheckAnnotations', () => {
  it('calls gh api with correct arguments', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '{"title":"error","message":"test failed","level":"failure"}' })
    const result = await fetchCheckAnnotations({ repo: 'org/repo', runId: '12345', exec })
    expect(exec).toHaveBeenCalledWith('gh', expect.arrayContaining(['api', 'repos/org/repo/check-runs/12345/annotations']))
    expect(result).toHaveLength(1)
  })

  it('handles multiple annotations', async () => {
    const exec = vi.fn().mockResolvedValue({
      stdout: '{"title":"error1"}\n{"title":"error2"}'
    })
    const result = await fetchCheckAnnotations({ repo: 'org/repo', runId: '12345', exec })
    expect(result).toHaveLength(2)
  })

  it('returns empty array on error or missing args', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('failed'))
    expect(await fetchCheckAnnotations({ repo: 'org/repo', runId: '12345', exec })).toEqual([])
    expect(await fetchCheckAnnotations({})).toEqual([])
  })
})

describe('classifyFailingChecks', () => {
  it('classifies no-runner checks separately from other failures', async () => {
    const checkRuns = [
      { name: 'iOS', status: 'COMPLETED', conclusion: 'SKIPPED' },
      { name: 'Web', status: 'COMPLETED', conclusion: 'FAILURE' }
    ]
    const exec = vi.fn().mockResolvedValue({ stdout: checkRuns.map(c => JSON.stringify(c)).join('\n') })
    const result = await classifyFailingChecks({
      repo: 'org/repo',
      sha: 'e'.repeat(40),
      failingNames: ['iOS', 'Web'],
      exec
    })
    expect(result.noRunner).toContain('iOS')
    expect(result.other).toContain('Web')
  })

  it('rejects false positive "skipped" in test summary (defect: heuristic too broad)', async () => {
    // A check that FAILED but its summary mentions "1 skipped, 2 failed" should NOT be classified as no-runner
    const checkRuns = [{
      name: 'pytest',
      status: 'COMPLETED',
      conclusion: 'FAILURE',
      id: '123',
      summary: 'Tests run: 3 passed, 1 skipped, 2 failed'
    }]
    const exec = vi.fn()
      .mockResolvedValueOnce({ stdout: checkRuns.map(c => JSON.stringify(c)).join('\n') })
      .mockResolvedValueOnce({ stdout: '' }) // no annotations

    const result = await classifyFailingChecks({
      repo: 'org/repo',
      sha: 'e'.repeat(40),
      failingNames: ['pytest'],
      exec
    })
    expect(result.noRunner).toEqual([])
    expect(result.other).toContain('pytest')
  })

  it('rejects false positive "unsupported" in error message (defect: heuristic too broad)', async () => {
    // A check that FAILED with "TypeError: unsupported operand" should NOT be classified as no-runner
    const checkRuns = [{
      name: 'lint',
      status: 'COMPLETED',
      conclusion: 'FAILURE',
      id: '456'
    }]
    const annotations = [{
      title: 'Error',
      message: 'TypeError: unsupported operand type(s) for +: "int" and "str"'
    }]
    const exec = vi.fn()
      .mockResolvedValueOnce({ stdout: JSON.stringify(checkRuns[0]) })
      .mockResolvedValueOnce({ stdout: JSON.stringify(annotations[0]) })

    const result = await classifyFailingChecks({
      repo: 'org/repo',
      sha: 'e'.repeat(40),
      failingNames: ['lint'],
      exec
    })
    expect(result.noRunner).toEqual([])
    expect(result.other).toContain('lint')
  })

  it('recognizes legitimate no-runner via annotation even with FAILURE conclusion', async () => {
    // A check with conclusion FAILURE but annotation saying "platform not available" IS a no-runner check
    const checkRuns = [{
      name: 'macos-build',
      status: 'COMPLETED',
      conclusion: 'FAILURE',
      id: '789'
    }]
    const annotations = [{
      title: 'Skipped',
      message: 'macOS runner not available on this plan'
    }]
    const exec = vi.fn()
      .mockResolvedValueOnce({ stdout: JSON.stringify(checkRuns[0]) })
      .mockResolvedValueOnce({ stdout: JSON.stringify(annotations[0]) })

    const result = await classifyFailingChecks({
      repo: 'org/repo',
      sha: 'e'.repeat(40),
      failingNames: ['macos-build'],
      exec
    })
    // FAILURE + annotation about platform unavailability = no-runner, not a real failure
    expect(result.noRunner).toContain('macos-build')
    expect(result.other).toEqual([])
  })

  it('recognizes SKIPPED conclusion as no-runner regardless of message', async () => {
    // A check with SKIPPED conclusion is always no-runner
    const checkRuns = [{
      name: 'optional-windows',
      status: 'COMPLETED',
      conclusion: 'SKIPPED',
      id: '999',
      summary: 'This check failed but was skipped'
    }]
    const exec = vi.fn()
      .mockResolvedValueOnce({ stdout: JSON.stringify(checkRuns[0]) })

    const result = await classifyFailingChecks({
      repo: 'org/repo',
      sha: 'e'.repeat(40),
      failingNames: ['optional-windows'],
      exec
    })
    expect(result.noRunner).toContain('optional-windows')
    expect(result.other).toEqual([])
  })

  it('falls back to treating unfound checks as other', async () => {
    // A check that isn't found in the commit's check runs is treated as "other"
    const checkRuns = JSON.stringify({ name: 'some-other-check', id: '999', status: 'COMPLETED', conclusion: 'FAILURE' })
    const exec = vi.fn().mockResolvedValue({ stdout: checkRuns })

    const result = await classifyFailingChecks({
      repo: 'org/repo',
      sha: 'f'.repeat(40),
      failingNames: ['unfound-check'],
      exec
    })

    expect(result.noRunner).toEqual([])
    expect(result.other).toContain('unfound-check')
  })

  it('defaults to other on API errors', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('failed'))
    const result = await classifyFailingChecks({
      repo: 'org/repo',
      sha: 'g'.repeat(40),
      failingNames: ['check1', 'check2'],
      exec
    })
    expect(result.noRunner).toEqual([])
    expect(result.other).toEqual(['check1', 'check2'])
  })

  it('handles empty or missing failing names', async () => {
    const exec = vi.fn()
    expect(await classifyFailingChecks({ repo: 'org/repo', sha: 'h'.repeat(40), failingNames: [], exec }))
      .toEqual({ noRunner: [], other: [] })
    expect(await classifyFailingChecks({ repo: 'org/repo', sha: 'h'.repeat(40), failingNames: null, exec }))
      .toEqual({ noRunner: [], other: [] })
  })
})
