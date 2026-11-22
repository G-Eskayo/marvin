import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { MergeFailure, refusal } from './failure.js'
import { ciState, checkRuns, gateCheckNames, requiredCheckNames, currentHeadSha, postGateStatus, waitForRequiredChecks, REQUIRED_CHECKS_TIMEOUT_MS, REQUIRED_CHECKS_POLL_MS } from './ci_status.js'

const tmp = () => mkdtempSync(path.join(tmpdir(), 'ci_status-'))

describe('ciState', () => {
  it('filters passing/failing/pending with no args', () => {
    const rollup = [
      { name: 'test1', status: 'COMPLETED', conclusion: 'SUCCESS' },
      { name: 'test2', status: 'IN_PROGRESS' },
      { name: 'test3', status: 'COMPLETED', conclusion: 'FAILURE' }
    ]
    const result = ciState(rollup)
    expect(result.state).toBe('failing')
    expect(result.failing).toContain('test3')
    expect(result.pending).toContain('test2')
    expect(result.pending).not.toContain('test1')
  })

  it('ignores checks by name', () => {
    const rollup = [
      { name: 'gate-check', status: 'COMPLETED', conclusion: 'FAILURE' },
      { name: 'other', status: 'COMPLETED', conclusion: 'FAILURE' }
    ]
    const result = ciState(rollup, { ignore: ['gate-check'] })
    expect(result.failing).toEqual(['other'])
  })

  it('filters to only specified checks', () => {
    const rollup = [
      { name: 'required1', status: 'COMPLETED', conclusion: 'SUCCESS' },
      { name: 'required2', status: 'IN_PROGRESS' },
      { name: 'other', status: 'COMPLETED', conclusion: 'SUCCESS' }
    ]
    const result = ciState(rollup, { only: ['required1', 'required2'] })
    expect(result.pending).toEqual(['required2'])
    expect(result.failing).toEqual([])
    expect(result.state).toBe('pending')
  })

  it('combines ignore and only', () => {
    const rollup = [
      { name: 'required1', status: 'COMPLETED', conclusion: 'SUCCESS' },
      { name: 'skip-me', status: 'COMPLETED', conclusion: 'FAILURE' },
      { name: 'other', status: 'COMPLETED', conclusion: 'FAILURE' }
    ]
    const result = ciState(rollup, { ignore: ['skip-me'], only: ['required1', 'skip-me', 'other'] })
    expect(result.failing).toEqual(['other'])
    expect(result.state).toBe('failing')
  })

  it('handles StatusContext type (commit statuses)', () => {
    const rollup = [
      { __typename: 'StatusContext', context: 'status1', state: 'SUCCESS' },
      { __typename: 'StatusContext', context: 'status2', state: 'PENDING' },
      { __typename: 'StatusContext', context: 'status3', state: 'FAILURE' }
    ]
    const result = ciState(rollup)
    expect(result.state).toBe('failing')
    expect(result.failing).toContain('status3')
    expect(result.pending).toContain('status2')
  })

  it('returns none when rollup is empty or null', () => {
    expect(ciState([])).toEqual({ state: 'none', failing: [], pending: [] })
    expect(ciState(null)).toEqual({ state: 'none', failing: [], pending: [] })
    expect(ciState(undefined)).toEqual({ state: 'none', failing: [], pending: [] })
  })
})

describe('checkRuns', () => {
  it('returns check rows with status and timing', () => {
    const rollup = [
      { name: 'test1', status: 'COMPLETED', conclusion: 'SUCCESS', startedAt: '2026-01-01T00:00:00Z', completedAt: '2026-01-01T00:01:00Z' }
    ]
    const rows = checkRuns(rollup)
    expect(rows).toHaveLength(1)
    expect(rows[0].name).toBe('test1')
    expect(rows[0].status).toBe('passed')
    expect(rows[0].done).toBe(true)
  })

  it('picks the newer run when duplicated', () => {
    const rollup = [
      { name: 'test', status: 'COMPLETED', conclusion: 'FAILURE', startedAt: '2026-01-01T00:00:00Z' },
      { name: 'test', status: 'COMPLETED', conclusion: 'SUCCESS', startedAt: '2026-01-01T00:05:00Z' }
    ]
    const rows = checkRuns(rollup)
    expect(rows).toHaveLength(1)
    expect(rows[0].status).toBe('passed')
  })
})

describe('gateCheckNames and requiredCheckNames', () => {
  it('returns gate checks (where: both or unset)', () => {
    const d = tmp()
    try {
      mkdirSync(path.join(d, '.github'), { recursive: true })
      const cfg = {
        checks: [
          { name: 'gate1', where: 'both' },
          { name: 'gate2' },  // defaults to 'both'
          { name: 'ci-only', where: 'ci-only' },
          { name: 'invalid' }  // no where field, still included as default
        ]
      }
      writeFileSync(path.join(d, '.github', 'required-checks.json'), JSON.stringify(cfg))
      expect(gateCheckNames(d)).toEqual(['gate1', 'gate2', 'invalid'])
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('returns all check names for requiredCheckNames', () => {
    const d = tmp()
    try {
      mkdirSync(path.join(d, '.github'), { recursive: true })
      const cfg = {
        checks: [
          { name: 'gate1', where: 'both' },
          { name: 'ci-only', where: 'ci-only' },
          { name: 'ci-only2', where: 'ci-only' }
        ]
      }
      writeFileSync(path.join(d, '.github', 'required-checks.json'), JSON.stringify(cfg))
      expect(requiredCheckNames(d)).toEqual(['gate1', 'ci-only', 'ci-only2'])
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('returns [] when file is unreadable', () => {
    const d = tmp()
    try {
      expect(gateCheckNames(d)).toEqual([])
      expect(requiredCheckNames(d)).toEqual([])
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('returns [] when checks is not an array', () => {
    const d = tmp()
    try {
      mkdirSync(path.join(d, '.github'), { recursive: true })
      writeFileSync(path.join(d, '.github', 'required-checks.json'), JSON.stringify({ checks: 'not an array' }))
      expect(gateCheckNames(d)).toEqual([])
      expect(requiredCheckNames(d)).toEqual([])
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})

describe('currentHeadSha', () => {
  it('returns a valid SHA', async () => {
    const exec = vi.fn(async () => ({ stdout: '0123456789abcdef0123456789abcdef01234567' }))
    const sha = await currentHeadSha('https://github.com/o/r/pull/1', exec)
    expect(sha).toBe('0123456789abcdef0123456789abcdef01234567')
  })

  it('returns empty string on invalid SHA', async () => {
    const exec = vi.fn(async () => ({ stdout: 'not-a-sha' }))
    const sha = await currentHeadSha('https://github.com/o/r/pull/1', exec)
    expect(sha).toBe('')
  })

  it('returns empty string on exec failure', async () => {
    const exec = vi.fn(async () => { throw new Error('gh failed') })
    const sha = await currentHeadSha('https://github.com/o/r/pull/1', exec)
    expect(sha).toBe('')
  })

  it('trims whitespace', async () => {
    const exec = vi.fn(async () => ({ stdout: '\n0123456789abcdef0123456789abcdef01234567\n' }))
    const sha = await currentHeadSha('https://github.com/o/r/pull/1', exec)
    expect(sha).toBe('0123456789abcdef0123456789abcdef01234567')
  })
})

describe('postGateStatus', () => {
  it('posts a success status with gate check names', async () => {
    let callCount = 0
    const exec = vi.fn(async (cmd, args) => {
      if (cmd === 'gh' && args[0] === 'pr' && args[1] === 'view' && args[2] === 'https://github.com/o/r/pull/1') {
        callCount++
        // currentHeadSha expects the SHA to be returned from --json headRefOid --jq
        if (args.includes('--jq')) {
          return { stdout: '0123456789abcdef0123456789abcdef01234567' }
        }
        // For JSON API call
        return { stdout: JSON.stringify({ headRefOid: '0123456789abcdef0123456789abcdef01234567' }) }
      }
      return { stdout: '' }
    })
    const result = await postGateStatus('https://github.com/o/r/pull/1', exec, ['check1', 'check2'])
    expect(result).toBe(true)
    expect(exec).toHaveBeenCalledWith('gh', expect.arrayContaining(['api']))
    const apiCall = exec.mock.calls.find((c) => c[0] === 'gh' && c[1][0] === 'api')
    expect(apiCall[1]).toContain('state=success')
    expect(apiCall[1]).toContain('context=MARVIN gate')
    expect(apiCall[1].some((a) => a.includes('check1, check2'))).toBe(true)
  })

  it('uses provided sha when given', async () => {
    const exec = vi.fn(async () => ({ stdout: '' }))
    const sha = '0123456789abcdef0123456789abcdef01234567'
    await postGateStatus('https://github.com/o/r/pull/1', exec, ['check1'], sha)
    const apiCall = exec.mock.calls.find((c) => c[0] === 'gh' && c[1][0] === 'api')
    expect(apiCall[1]).toContain(`repos/o/r/statuses/${sha}`)
  })

  it('fetches sha if not provided', async () => {
    let callCount = 0
    const exec = vi.fn(async (cmd, args) => {
      if (cmd === 'gh' && args[0] === 'pr' && args[1] === 'view' && callCount === 0) {
        callCount++
        return { stdout: JSON.stringify({ headRefOid: '0123456789abcdef0123456789abcdef01234567' }) }
      }
      return { stdout: '' }
    })
    await postGateStatus('https://github.com/o/r/pull/1', exec, ['check1'])
    expect(exec).toHaveBeenCalledWith('gh', expect.arrayContaining(['pr', 'view']))
  })

  it('returns false on invalid PR URL', async () => {
    const exec = vi.fn()
    const result = await postGateStatus('not-a-url', exec, [])
    expect(result).toBe(false)
    expect(exec).not.toHaveBeenCalled()
  })

  it('returns false on exec failure', async () => {
    const exec = vi.fn(async () => { throw new Error('gh failed') })
    const result = await postGateStatus('https://github.com/o/r/pull/1', exec, [])
    expect(result).toBe(false)
  })
})

describe('waitForRequiredChecks', () => {
  it('resolves immediately when all required checks pass', async () => {
    const exec = vi.fn(async () => ({
      stdout: JSON.stringify({
        headRefOid: 'sha123',
        statusCheckRollup: [
          { name: 'check1', status: 'COMPLETED', conclusion: 'SUCCESS' }
        ]
      })
    }))
    await waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
      sha: 'sha123',
      names: ['check1'],
      now: () => 0,
      sleep: vi.fn()
    })
    expect(exec).toHaveBeenCalled()
  })

  it('polls until checks pass', async () => {
    const exec = vi.fn(async () => ({
      stdout: JSON.stringify({
        headRefOid: 'sha123',
        statusCheckRollup: [
          { name: 'check1', status: exec.mock.calls.length < 2 ? 'IN_PROGRESS' : 'COMPLETED', conclusion: 'SUCCESS' }
        ]
      })
    }))
    const sleep = vi.fn(async () => {})
    const now = vi.fn(() => 0)
    await waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
      sha: 'sha123',
      names: ['check1'],
      pollMs: 1000,
      now,
      sleep
    })
    expect(exec.mock.calls.length).toBeGreaterThan(1)
    expect(sleep).toHaveBeenCalled()
  })

  it('throws CI_FAILED when a check fails', async () => {
    const exec = vi.fn(async () => ({
      stdout: JSON.stringify({
        headRefOid: 'sha123',
        statusCheckRollup: [
          { name: 'check1', status: 'COMPLETED', conclusion: 'FAILURE' }
        ]
      })
    }))
    await expect(
      waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
        sha: 'sha123',
        names: ['check1']
      })
    ).rejects.toThrow()
    try {
      await waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
        sha: 'sha123',
        names: ['check1']
      })
    } catch (e) {
      expect(e).toBeInstanceOf(MergeFailure)
      expect(e.payload.code).toBe('CI_FAILED')
      expect(e.payload.action).toBe('reengage')
    }
  })

  it('throws HEAD_MOVED when SHA changes', async () => {
    const exec = vi.fn(async () => ({
      stdout: JSON.stringify({
        headRefOid: 'newsha456',
        statusCheckRollup: []
      })
    }))
    await expect(
      waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
        sha: 'oldsha123',
        names: []
      })
    ).rejects.toThrow()
    try {
      await waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
        sha: 'oldsha123',
        names: []
      })
    } catch (e) {
      expect(e).toBeInstanceOf(MergeFailure)
      expect(e.payload.code).toBe('HEAD_MOVED')
      expect(e.payload.action).toBe('retry')
    }
  })

  it('throws CI_TIMEOUT when deadline expires', async () => {
    const exec = vi.fn(async () => ({
      stdout: JSON.stringify({
        headRefOid: 'sha123',
        statusCheckRollup: [
          { name: 'check1', status: 'IN_PROGRESS' }
        ]
      })
    }))
    const times = [0, 1000, 10 * 60_000]
    let callCount = 0
    const now = vi.fn(() => times[Math.min(callCount++, times.length - 1)])
    const sleep = vi.fn(async () => {})
    await expect(
      waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
        sha: 'sha123',
        names: ['check1'],
        timeoutMs: 5 * 60_000,
        pollMs: 1000,
        now,
        sleep
      })
    ).rejects.toThrow()
    try {
      callCount = 0
      await waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
        sha: 'sha123',
        names: ['check1'],
        timeoutMs: 5 * 60_000,
        pollMs: 1000,
        now,
        sleep
      })
    } catch (e) {
      expect(e).toBeInstanceOf(MergeFailure)
      expect(e.payload.code).toBe('CI_TIMEOUT')
      expect(e.payload.action).toBe('retry')
    }
  })

  it('filters checks using only parameter', async () => {
    const exec = vi.fn(async () => ({
      stdout: JSON.stringify({
        headRefOid: 'sha123',
        statusCheckRollup: [
          { name: 'required1', status: 'COMPLETED', conclusion: 'SUCCESS' },
          { name: 'other', status: 'IN_PROGRESS' }
        ]
      })
    }))
    const sleep = vi.fn()
    await waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
      sha: 'sha123',
      names: ['required1'],  // only wait for required1, ignore other
      now: () => 0,
      sleep
    })
    expect(sleep).not.toHaveBeenCalled()  // should resolve immediately
  })

  it('handles missing initial SHA by fetching it', async () => {
    const validSha = '0123456789abcdef0123456789abcdef01234567'
    let callCount = 0
    const exec = vi.fn(async (cmd, args) => {
      if (cmd === 'gh' && args[0] === 'pr' && args[1] === 'view') {
        callCount++
        if (callCount === 1 && args.includes('--jq')) {
          // First call: get SHA (called by currentHeadSha via --json headRefOid --jq)
          return { stdout: validSha }
        }
        // Second+ calls: get status rollup (via --json headRefOid,statusCheckRollup)
        return {
          stdout: JSON.stringify({
            headRefOid: validSha,
            statusCheckRollup: [
              { name: 'check1', status: 'COMPLETED', conclusion: 'SUCCESS' }
            ]
          })
        }
      }
      return { stdout: '' }
    })
    await waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
      names: ['check1']
    })
    expect(exec.mock.calls.length).toBeGreaterThan(1)
  })

  it('throws HEAD_MOVED when initial SHA fetch fails', async () => {
    const exec = vi.fn(async () => { throw new Error('gh failed') })
    await expect(
      waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
        names: ['check1']
      })
    ).rejects.toThrow()
    try {
      await waitForRequiredChecks('https://github.com/o/r/pull/1', exec, {
        names: ['check1']
      })
    } catch (e) {
      expect(e).toBeInstanceOf(MergeFailure)
      expect(e.payload.code).toBe('HEAD_MOVED')
      expect(e.payload.action).toBe('retry')
    }
  })
})
