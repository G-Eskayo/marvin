import { describe, it, expect, vi, afterEach } from 'vitest'
import { readNoRunnerReruns, recordNoRunnerRerun, triggerNoRunnerRerun, handleNoRunnerRerunRequest } from '../webhook-server/no_runner_rerun.js'
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'fs'
import path from 'path'
import os from 'os'

describe('readNoRunnerReruns', () => {
  it('returns empty object for missing file', () => {
    expect(readNoRunnerReruns('/nonexistent/path.json')).toEqual({})
  })

  it('parses existing JSON file', () => {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'no-runner-'))
    const file = path.join(dir, 'reruns.json')
    writeFileSync(file, JSON.stringify({ 'https://github.com/o/r/pull/1': { pr: 1, rerun: 'started' } }))
    expect(readNoRunnerReruns(file)).toEqual({ 'https://github.com/o/r/pull/1': { pr: 1, rerun: 'started' } })
    rmSync(dir, { recursive: true })
  })

  it('handles corrupt JSON gracefully', () => {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'no-runner-'))
    const file = path.join(dir, 'reruns.json')
    writeFileSync(file, 'not json')
    expect(readNoRunnerReruns(file)).toEqual({})
    rmSync(dir, { recursive: true })
  })
})

describe('recordNoRunnerRerun', () => {
  it('records new entries and prunes old ones', () => {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'no-runner-'))
    const file = path.join(dir, 'reruns.json')
    const now = new Date()
    const eightDaysAgo = new Date(now.getTime() - 8 * 24 * 60 * 60 * 1000)

    // Write old entry
    writeFileSync(file, JSON.stringify({
      'https://github.com/o/r/pull/old': { pr: 1, at: eightDaysAgo.toISOString() }
    }))

    // Record new entry
    recordNoRunnerRerun([{
      url: 'https://github.com/o/r/pull/2',
      pr: 2,
      repo: 'o/r',
      sha: 'a'.repeat(40),
      runId: '999',
      rerun: 'started',
      at: now.toISOString()
    }], file, () => now)

    const data = JSON.parse(readFileSync(file, 'utf-8'))
    expect(data['https://github.com/o/r/pull/old']).toBeUndefined()
    expect(data['https://github.com/o/r/pull/2']).toBeDefined()
    expect(data['https://github.com/o/r/pull/2'].pr).toBe(2)
    rmSync(dir, { recursive: true })
  })

  it('updates existing entries', () => {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'no-runner-'))
    const file = path.join(dir, 'reruns.json')
    const now = new Date()

    writeFileSync(file, JSON.stringify({
      'https://github.com/o/r/pull/1': { pr: 1, rerun: 'started', at: new Date(now - 1000).toISOString() }
    }))

    recordNoRunnerRerun([{
      url: 'https://github.com/o/r/pull/1',
      pr: 1,
      rerun: 'already-tried',
      at: now.toISOString()
    }], file, () => now)

    const data = JSON.parse(readFileSync(file, 'utf-8'))
    expect(data['https://github.com/o/r/pull/1'].rerun).toBe('already-tried')
    rmSync(dir, { recursive: true })
  })
})

describe('triggerNoRunnerRerun', () => {
  it('calls gh api to rerun the action', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '' })
    const dir = mkdtempSync(path.join(os.tmpdir(), 'no-runner-'))
    const file = path.join(dir, 'reruns.json')

    const result = await triggerNoRunnerRerun({
      repo: 'o/r',
      number: 42,
      sha: 'a'.repeat(40),
      runId: '12345',
      checkName: 'iOS Tests',
      exec,
      file
    })

    expect(result.ok).toBe(true)
    expect(result.rerun).toBe('started')
    expect(exec).toHaveBeenCalledWith('gh', ['api', 'repos/o/r/actions/runs/12345/rerun', '-X', 'POST'])

    // Check that it was recorded
    const data = JSON.parse(readFileSync(file, 'utf-8'))
    expect(Object.values(data)[0]?.rerun).toBe('started')
    rmSync(dir, { recursive: true })
  })

  it('deduplicates reruns for the same check at the same commit (defect: no dedup)', async () => {
    // If a rerun was already started for this check at this commit, don't trigger again
    const exec = vi.fn().mockResolvedValue({ stdout: '' })
    const dir = mkdtempSync(path.join(os.tmpdir(), 'no-runner-'))
    const file = path.join(dir, 'reruns.json')

    // First rerun
    const result1 = await triggerNoRunnerRerun({
      repo: 'o/r',
      number: 42,
      sha: 'a'.repeat(40),
      runId: '12345',
      checkName: 'iOS Tests',
      exec,
      file
    })

    expect(result1.ok).toBe(true)
    expect(exec).toHaveBeenCalledTimes(1)

    // Second rerun of the same check at same commit should deduplicate
    const result2 = await triggerNoRunnerRerun({
      repo: 'o/r',
      number: 42,
      sha: 'a'.repeat(40),
      runId: '12345',
      checkName: 'iOS Tests',
      exec,
      file
    })

    expect(result2.ok).toBe(true)
    expect(result2.rerun).toBe('already-tried')
    expect(exec).toHaveBeenCalledTimes(1) // Not called again
    rmSync(dir, { recursive: true })
  })

  it('allows independent reruns for different checks at same commit', async () => {
    // Different checks at the same commit should trigger independently
    const exec = vi.fn().mockResolvedValue({ stdout: '' })
    const dir = mkdtempSync(path.join(os.tmpdir(), 'no-runner-'))
    const file = path.join(dir, 'reruns.json')

    const result1 = await triggerNoRunnerRerun({
      repo: 'o/r',
      number: 42,
      sha: 'a'.repeat(40),
      runId: '12345',
      checkName: 'iOS Tests',
      exec,
      file
    })

    expect(result1.ok).toBe(true)
    expect(exec).toHaveBeenCalledTimes(1)

    const result2 = await triggerNoRunnerRerun({
      repo: 'o/r',
      number: 42,
      sha: 'a'.repeat(40),
      runId: '12345',
      checkName: 'macOS Tests', // Different check
      exec,
      file
    })

    expect(result2.ok).toBe(true)
    expect(exec).toHaveBeenCalledTimes(2) // Called again for different check
    rmSync(dir, { recursive: true })
  })

  it('records failure when rerun fails', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('403 Forbidden'))
    const dir = mkdtempSync(path.join(os.tmpdir(), 'no-runner-'))
    const file = path.join(dir, 'reruns.json')

    const result = await triggerNoRunnerRerun({
      repo: 'o/r',
      number: 42,
      sha: 'a'.repeat(40),
      runId: '12345',
      exec,
      file
    })

    expect(result.ok).toBe(false)
    expect(result.rerun).toBe('already-tried')

    // Check that it was recorded as failure
    const data = JSON.parse(readFileSync(file, 'utf-8'))
    expect(Object.values(data)[0]?.rerun).toBe('already-tried')
    rmSync(dir, { recursive: true })
  })

  it('returns error for missing arguments', async () => {
    const exec = vi.fn()
    const result = await triggerNoRunnerRerun({ repo: 'o/r', number: 42, sha: '', runId: '123', exec })
    expect(result.ok).toBe(false)
    expect(exec).not.toHaveBeenCalled()
  })
})

describe('handleNoRunnerRerunRequest', () => {
  const baseRequest = {
    method: 'POST',
    url: '/no-runner-rerun',
    body: JSON.stringify({
      pr_url: 'https://github.com/o/r/pull/42',
      number: 42,
      sha: 'a'.repeat(40),
      runId: '12345',
      checkName: 'iOS Tests'
    })
  }

  it('handles valid rerun request', async () => {
    // Mock: first call validates runId (returns matching id), second call triggers rerun
    const exec = vi.fn()
      .mockResolvedValueOnce({ stdout: '12345' }) // validation: found matching runId
      .mockResolvedValueOnce({}) // actual rerun trigger
    const dir = mkdtempSync(path.join(os.tmpdir(), 'no-runner-'))
    const file = path.join(dir, 'reruns.json')

    const { status, json } = await handleNoRunnerRerunRequest(baseRequest, { exec, file, knownRepos: ['o/r'] })
    expect(status).toBe(200)
    expect(json.ok).toBe(true)
    expect(json.rerun).toBe('started')
    rmSync(dir, { recursive: true })
  })

  it('rejects non-POST requests', async () => {
    const { status, json } = await handleNoRunnerRerunRequest({ method: 'GET', url: '/no-runner-rerun' })
    expect(status).toBe(404)
    expect(json.ok).toBe(false)
  })

  it('rejects wrong URL', async () => {
    const { status, json } = await handleNoRunnerRerunRequest({ method: 'POST', url: '/other' })
    expect(status).toBe(404)
  })

  it('rejects invalid JSON body', async () => {
    const { status, json } = await handleNoRunnerRerunRequest({
      method: 'POST',
      url: '/no-runner-rerun',
      body: 'not json'
    })
    expect(status).toBe(400)
    expect(json.ok).toBe(false)
  })

  it('rejects missing required fields', async () => {
    const cases = [
      { pr_url: 'https://github.com/o/r/pull/42' }, // missing number, sha, runId, checkName
      { number: 42, sha: 'a'.repeat(40) }, // missing pr_url, runId, checkName
      { pr_url: 'https://github.com/o/r/pull/42', number: 42, sha: 'a'.repeat(40), runId: '123' }, // missing checkName
      { pr_url: 'https://github.com/o/r/pull/42', number: 42, sha: 'a'.repeat(40), checkName: 'test' } // missing runId
    ]
    for (const body of cases) {
      const { status, json } = await handleNoRunnerRerunRequest({
        method: 'POST',
        url: '/no-runner-rerun',
        body: JSON.stringify(body)
      })
      expect(status).toBe(400)
      expect(json.ok).toBe(false)
      expect(json.error).toMatch(/missing required/)
    }
  })

  it('rejects requests from unknown repos (security)', async () => {
    const { status, json } = await handleNoRunnerRerunRequest(baseRequest, { exec: vi.fn(), knownRepos: ['other/repo'] })
    expect(status).toBe(403)
    expect(json.ok).toBe(false)
    expect(json.error).toMatch(/not a known repo/)
  })

  it('rejects invalid pr_url', async () => {
    const { status, json } = await handleNoRunnerRerunRequest({
      method: 'POST',
      url: '/no-runner-rerun',
      body: JSON.stringify({
        pr_url: 'not-a-url',
        number: 42,
        sha: 'a'.repeat(40),
        runId: '12345',
        checkName: 'test'
      })
    }, { knownRepos: ['o/r'] })
    expect(status).toBe(400)
    expect(json.error).toMatch(/invalid pr_url/)
  })

  it('handles exec errors gracefully', async () => {
    // Validation fails (API error), so we return 400 for validation failure
    const exec = vi.fn().mockRejectedValue(new Error('API unavailable'))
    const dir = mkdtempSync(path.join(os.tmpdir(), 'no-runner-'))
    const file = path.join(dir, 'reruns.json')

    const { status, json } = await handleNoRunnerRerunRequest(baseRequest, { exec, file, knownRepos: ['o/r'] })
    expect(status).toBe(400)
    expect(json.error).toMatch(/could not validate/)
    rmSync(dir, { recursive: true })
  })
})
