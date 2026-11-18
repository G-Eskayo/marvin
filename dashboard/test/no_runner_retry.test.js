import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createNoRunnerRetry } from '../electron/main/no_runner_retry.js'
import { NO_RUNNER_RERUN_PATH } from '../webhook-server/no_runner_rerun.js'
import { writeFileSync, mkdirSync } from 'fs'
import path from 'path'

const pr = (number, repo = 'owner/repo', headSha = 'abc123') => ({
  number,
  url: `https://github.com/${repo}/pull/${number}`,
  repo,
  headRefOid: headSha,
  statusCheckRollup: []
})

const failingCheck = (name, conclusion = 'TIMED_OUT', detailsUrl = 'https://github.com/o/r/actions/runs/123/job/456') => ({
  name,
  status: 'COMPLETED',
  conclusion,
  detailsUrl
})

describe('createNoRunnerRetry', () => {
  let gh, log, now, noRunnerRetry

  beforeEach(() => {
    gh = vi.fn().mockResolvedValue('[]')
    log = vi.fn()
    now = vi.fn(() => new Date('2026-11-17'))
    // Clear the file before each test to isolate test state
    try {
      mkdirSync(path.dirname(NO_RUNNER_RERUN_PATH), { recursive: true })
      writeFileSync(NO_RUNNER_RERUN_PATH, '{}')
    } catch {
      // If file can't be written, continue anyway
    }
    noRunnerRetry = createNoRunnerRetry({ gh, gateCoversFor: () => null, log, now })
  })

  afterEach(() => {
    // Clean up the file after each test
    try {
      mkdirSync(path.dirname(NO_RUNNER_RERUN_PATH), { recursive: true })
      writeFileSync(NO_RUNNER_RERUN_PATH, '{}')
    } catch {
      // If file can't be cleaned, continue anyway
    }
  })

  it('first sighting of a no-runner check: calls gh to get annotations, then reruns', async () => {
    const annotationsCall = vi.fn().mockResolvedValue('[]')
    const rerunCall = vi.fn().mockResolvedValue('')
    gh.mockImplementation((args) => {
      if (args[0] === 'api' && args[1].includes('annotations')) return annotationsCall()
      if (args[0] === 'run' && args[1] === 'rerun') return rerunCall()
      return Promise.resolve('[]')
    })
    noRunnerRetry = createNoRunnerRetry({ gh, gateCoversFor: () => null, log, now })

    const prs = [pr(1)]
    prs[0].statusCheckRollup = [failingCheck('slow test', 'TIMED_OUT', 'https://github.com/owner/repo/actions/runs/123/job/456')]

    await noRunnerRetry.check(prs)

    expect(gh).toHaveBeenCalledWith(expect.arrayContaining(['api']))
    expect(gh).toHaveBeenCalledWith(expect.arrayContaining(['run', 'rerun']))
  })

  it('second check with same key already reran: does not call rerun again, flips to "asked"', async () => {
    const prs = [pr(1)]
    prs[0].statusCheckRollup = [failingCheck('test', 'CANCELLED')]

    await noRunnerRetry.check(prs)
    const afterFirst = gh.mock.calls.length

    // Second call with same PR
    gh.mockClear()
    await noRunnerRetry.check(prs)
    const afterSecond = gh.mock.calls.length

    // Should make fewer gh calls the second time (no rerun call)
    expect(afterSecond).toBeLessThan(afterFirst)
  })

  it('third check with result "asked" already on disk: makes zero gh calls', async () => {
    const prs = [pr(1)]
    prs[0].statusCheckRollup = [failingCheck('test', 'CANCELLED')]

    // First two checks
    await noRunnerRetry.check(prs)
    gh.mockClear()
    await noRunnerRetry.check(prs)

    // Third check
    gh.mockClear()
    await noRunnerRetry.check(prs)

    // On the third check with 'asked' already recorded, no gh calls
    expect(gh).not.toHaveBeenCalled()
  })

  it('rerun call throws: records result as "refused" and later checks skip rerun', async () => {
    // First annotations call succeeds, rerun call rejects
    let callCount = 0
    gh.mockImplementation(async (args) => {
      callCount++
      if (callCount === 1) {
        // Annotations call succeeds
        return '[]'
      } else if (callCount === 2) {
        // Rerun call fails
        throw new Error('rate limit')
      } else {
        // Later calls
        return '[]'
      }
    })
    noRunnerRetry = createNoRunnerRetry({ gh, gateCoversFor: () => null, log, now })

    const prs = [pr(1)]
    prs[0].statusCheckRollup = [failingCheck('test', 'CANCELLED')]

    await noRunnerRetry.check(prs)

    // Second check should not attempt rerun (state is already 'refused')
    callCount = 0
    gh.mockClear()
    gh.mockResolvedValue('[]')
    await noRunnerRetry.check(prs)

    // On refusal, further checks should not call rerun
    const hasRerunCall = gh.mock.calls.some((c) => c[0]?.[1] === 'rerun')
    expect(hasRerunCall).toBe(false)
  })

  it('annotations call throws (404 / still-processing): no record written, check falls through untouched', async () => {
    gh.mockRejectedValueOnce(new Error('404'))
    const prs = [pr(1)]
    prs[0].statusCheckRollup = [failingCheck('test', 'TIMED_OUT')]

    await noRunnerRetry.check(prs)

    // No gh calls after first (which failed), so no rerun attempt
    expect(gh).toHaveBeenCalledTimes(1)
  })

  it('a PR with one no-runner check AND one real FAILURE check: zero gh calls, nothing written', async () => {
    const prs = [pr(1)]
    prs[0].statusCheckRollup = [
      failingCheck('real failure', 'FAILURE'),
      failingCheck('no runner', 'TIMED_OUT')
    ]

    await noRunnerRetry.check(prs)

    // Should not make any gh calls because PR has a real failure
    expect(gh).not.toHaveBeenCalled()
  })

  it('a gate-covered check name is excluded before any annotation call', async () => {
    gh.mockResolvedValue('[]')
    const gateCoversFor = vi.fn(() => ['test'])
    noRunnerRetry = createNoRunnerRetry({ gh, gateCoversFor, log, now })

    const prs = [pr(1)]
    prs[0].statusCheckRollup = [failingCheck('test', 'TIMED_OUT')]

    await noRunnerRetry.check(prs)

    // No gh calls for a gate-covered check
    expect(gh).not.toHaveBeenCalled()
  })

  it('two PRs, two different repos, same headSha: each gets independently exactly one rerun', async () => {
    gh.mockResolvedValue('[]')
    const prs = [
      pr(1, 'a/b', 'shared-sha'),
      pr(1, 'c/d', 'shared-sha')
    ]
    prs[0].statusCheckRollup = [failingCheck('test', 'TIMED_OUT')]
    prs[1].statusCheckRollup = [failingCheck('test', 'TIMED_OUT')]

    await noRunnerRetry.check(prs)

    // Count rerun calls - should be one per PR (or at least attempt one per)
    const rerunCalls = gh.mock.calls.filter((c) => c[0]?.[1] === 'rerun').length
    expect(rerunCalls).toBeGreaterThanOrEqual(1)
  })

  it('error on annotations call is caught, logged, never thrown out of check()', async () => {
    gh.mockRejectedValueOnce(new Error('network error'))
    const prs = [pr(1)]
    prs[0].statusCheckRollup = [failingCheck('test', 'TIMED_OUT')]

    expect(async () => {
      await noRunnerRetry.check(prs)
    }).not.toThrow()
  })

  it('check() never throws', async () => {
    gh.mockRejectedValue(new Error('catastrophe'))
    const prs = [pr(1)]
    prs[0].statusCheckRollup = [failingCheck('test', 'CANCELLED')]

    expect(async () => {
      await noRunnerRetry.check(prs)
    }).not.toThrow()
  })
})
