import { describe, it, expect, vi } from 'vitest'
import {
  classifyFailure,
  summarizeGateFailure,
  infraCause,
  withRetry,
  MergeFailure
} from '../webhook-server/failure.js'

// Approve failures used to reach the dashboard as "Webhook call failed: 500" and the
// pipeline as a raw stderr wall -- neither a human nor an automated consumer could act.
// Every failure now carries a stable CODE, the STAGE, whether it is RETRYABLE, and a
// next ACTION (retry | reengage | escalate) so the pipeline can retry, send the ticket
// back, or escalate without parsing prose.

const err = (message, extra = {}) => Object.assign(new Error(message), extra)

describe('classifyFailure', () => {
  it.each([
    ['HTTP 401: Bad credentials (https://api.github.com/graphql)', 'GH_AUTH_INVALID', 'escalate', false],
    ['fatal: could not read Username for https://github.com: Device not configured', 'GH_AUTH_INVALID', 'escalate', false],
    ['GraphQL: Pull request is not mergeable: merge conflict', 'NOT_MERGEABLE', 'reengage', false],
    ['remote: error: GH006: Protected branch update failed; required status check missing', 'BRANCH_PROTECTION', 'escalate', false],
    ['API rate limit exceeded for user', 'RATE_LIMITED', 'retry', true],
    ['connect ETIMEDOUT 140.82.112.6:443', 'TRANSIENT_NETWORK', 'retry', true],
    ['socket hang up', 'TRANSIENT_NETWORK', 'retry', true],
    ['HTTP 502: Bad Gateway', 'TRANSIENT_NETWORK', 'retry', true],
    ['remote: Internal Server Error', 'GITHUB_OUTAGE', 'retry', true],
    ['HTTP 500: Internal Server Error (https://api.github.com/graphql)', 'GITHUB_OUTAGE', 'retry', true],
    ['fatal: unable to access \'https://github.com/x/y.git/\': The requested URL returned error: 503', 'GITHUB_OUTAGE', 'retry', true],
    ['GraphQL: Base branch was modified. Review and try the merge again. (mergePullRequest)', 'BASE_MOVED', 'retry', true],
    ['spawn gh ENOENT', 'TOOL_MISSING', 'escalate', false],
    ['Not a GitHub PR URL: foo', 'INVALID_REQUEST', 'escalate', false],
    ['something nobody has seen before', 'UNKNOWN', 'escalate', false]
  ])('classifies %j as %s (%s, retryable=%s)', (message, code, action, retryable) => {
    const f = classifyFailure({ stage: 'merging', error: err(message) })
    expect(f.code).toBe(code)
    expect(f.action).toBe(action)
    expect(f.retryable).toBe(retryable)
    expect(f.stage).toBe('merging')
    expect(f.remediation).toBeTruthy()
  })

  it('reads stderr as well as the message, since execFile puts the real reason there', () => {
    const f = classifyFailure({ stage: 'merging', error: err('Command failed: gh pr merge', { stderr: 'HTTP 401: Bad credentials' }) })
    expect(f.code).toBe('GH_AUTH_INVALID')
  })

  it('uses the first meaningful stderr line as the message, not execFile\'s "Command failed:" boilerplate', () => {
    const e = err('Command failed: gh pr merge https://github.com/o/r/pull/9 --merge\nGraphQL: Could not resolve to a PullRequest', {
      stderr: 'GraphQL: Could not resolve to a PullRequest with the number of 9. (repository.pullRequest)\n'
    })
    const f = classifyFailure({ stage: 'merging', error: e })
    expect(f.message).toBe('GraphQL: Could not resolve to a PullRequest with the number of 9. (repository.pullRequest)')
  })

  it('gives a PR that cannot be found its own code', () => {
    const f = classifyFailure({ stage: 'merging', error: err('x', { stderr: 'GraphQL: Could not resolve to a PullRequest with the number of 9.' }) })
    expect(f.code).toBe('PR_NOT_FOUND')
    expect(f.action).toBe('escalate')
    expect(f.remediation).toMatch(/closed|deleted|URL/i)
  })

  it('keeps a short excerpt of the original text as evidence, capped', () => {
    const f = classifyFailure({ stage: 'merging', error: err('x'.repeat(5000)) })
    expect(f.evidence.length).toBeLessThanOrEqual(600)
  })
})

describe('summarizeGateFailure', () => {
  const pytestOut = [
    '....F.',
    'FAILED lib/tests/test_a.py::test_one - AssertionError: nope',
    'FAILED lib/tests/test_b.py::test_two - KeyError',
    '2 failed, 540 passed in 30.1s'
  ].join('\n')

  it('turns a rebase conflict into REBASE_CONFLICT with the conflicting output', () => {
    const s = summarizeGateFailure('Rebase onto main failed:\n\nCONFLICT (content): Merge conflict in lib/x.py')
    expect(s.code).toBe('REBASE_CONFLICT')
    expect(s.comment).toContain('REBASE_CONFLICT')
    expect(s.comment).toContain('lib/x.py')
  })

  it('turns a test failure into GATE_TESTS_FAILED and lists the failing tests by name', () => {
    const s = summarizeGateFailure(`Tests failed after rebasing onto main:\n\n${pytestOut}`)
    expect(s.code).toBe('GATE_TESTS_FAILED')
    expect(s.failingTests).toEqual(['lib/tests/test_a.py::test_one', 'lib/tests/test_b.py::test_two'])
    expect(s.comment).toContain('lib/tests/test_a.py::test_one')
    expect(s.comment).toContain('Failing tests (2)')
  })

  it('also recognises vitest failures', () => {
    const out = ' FAIL  test/merge.test.js > mergePr > routes to re-engagement\n × other thing\nTests  1 failed | 10 passed (11)'
    const s = summarizeGateFailure(`Tests failed after rebasing onto main:\n\n${out}`)
    expect(s.failingTests).toContain('test/merge.test.js > mergePr > routes to re-engagement')
  })

  it('caps a huge output wall to a readable tail', () => {
    const wall = Array.from({ length: 500 }, (_, i) => `line ${i}`).join('\n')
    const s = summarizeGateFailure(`Tests failed after rebasing onto main:\n\n${wall}`)
    expect(s.comment.length).toBeLessThan(4000)
    expect(s.comment).toContain('line 499')
    expect(s.comment).not.toContain('line 10\n')
  })

  it('returns a machine-readable header line the pipeline can parse', () => {
    const s = summarizeGateFailure(`Tests failed after rebasing onto main:\n\n${pytestOut}`)
    expect(s.comment.split('\n')[0]).toMatch(/^\*\*Merge gate: GATE_TESTS_FAILED\*\*/)
  })
})

describe('withRetry', () => {
  const classify = (e) => ({ retryable: /transient/.test(e.message) })

  it('returns the value on first success without sleeping', async () => {
    const sleep = vi.fn()
    const r = await withRetry(async () => 'ok', { classify, sleep })
    expect(r).toEqual({ value: 'ok', attempts: 1 })
    expect(sleep).not.toHaveBeenCalled()
  })

  it('retries a retryable failure with growing backoff, then succeeds', async () => {
    const sleep = vi.fn()
    let n = 0
    const fn = async () => { if (++n < 3) throw err('transient'); return 'ok' }
    const r = await withRetry(fn, { classify, sleep, baseMs: 100 })
    expect(r.attempts).toBe(3)
    expect(sleep.mock.calls.map((c) => c[0])).toEqual([100, 200])
  })

  it('does not retry a non-retryable failure', async () => {
    const fn = vi.fn().mockRejectedValue(err('bad credentials'))
    await expect(withRetry(fn, { classify, sleep: vi.fn() })).rejects.toMatchObject({ attempts: 1 })
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('gives up after the retry budget and reports how many attempts it made', async () => {
    const fn = vi.fn().mockRejectedValue(err('transient'))
    await expect(withRetry(fn, { classify, sleep: vi.fn(), retries: 3 })).rejects.toMatchObject({ attempts: 4 })
    expect(fn).toHaveBeenCalledTimes(4)
  })
})

describe('MergeFailure', () => {
  it('is an Error whose message carries the code and the original text, and exposes the payload', () => {
    const f = new MergeFailure({ code: 'GH_AUTH_INVALID', stage: 'merging', message: 'Bad credentials', action: 'escalate', retryable: false, remediation: 'fix it' })
    expect(f).toBeInstanceOf(Error)
    expect(f.message).toContain('GH_AUTH_INVALID')
    expect(f.message).toContain('Bad credentials')
    expect(f.payload.action).toBe('escalate')
  })
})

import { failureResponse } from '../webhook-server/failure.js'

describe('failureResponse', () => {
  it('shapes a MergeFailure into a JSON body that keeps the legacy `error`/`merged` keys', () => {
    const f = new MergeFailure({ code: 'GH_AUTH_INVALID', stage: 'merging', message: 'Bad credentials', action: 'escalate',
                                 retryable: false, remediation: 'fix token', evidence: 'e', attempts: 1 })
    const { status, body } = failureResponse(f)
    expect(status).toBe(500)
    expect(body).toMatchObject({ merged: false, code: 'GH_AUTH_INVALID', stage: 'merging', action: 'escalate', remediation: 'fix token' })
    expect(body.error).toContain('GH_AUTH_INVALID')
  })

  it('classifies an unexpected plain Error instead of leaking a bare message', () => {
    const { body } = failureResponse(new Error('HTTP 401: Bad credentials'))
    expect(body.code).toBe('GH_AUTH_INVALID')
    expect(body.merged).toBe(false)
  })
})

import { summarizeGateFailure as summarize, refusal } from '../webhook-server/failure.js'

describe('Swift gate failures and refusals', () => {
  it('names a failing XCTest so the ticket\'s executor knows which test to fix', () => {
    const reason = `Tests failed after rebasing onto main:\n\nTest Case '-[CaptionCoreTests.SpeakerAlignerTests testBad]' failed (0.1 seconds).\nTest Case '-[CaptionCoreTests.ThemeTests testWorse]' failed (0.0 seconds).\nExecuted 12 tests, with 2 failures`
    const s = summarize(reason)
    expect(s.code).toBe('GATE_TESTS_FAILED')
    expect(s.failingTests).toEqual(['CaptionCoreTests.SpeakerAlignerTests/testBad', 'CaptionCoreTests.ThemeTests/testWorse'])
  })

  it('builds a coded refusal that says what to do next', () => {
    const r = refusal('NO_MERGE_PROFILE', 'request', 'x has no profile', 'Add merge_from_dashboard to its profile.')
    expect(r).toMatchObject({ code: 'NO_MERGE_PROFILE', stage: 'request', action: 'escalate', retryable: false, remediation: expect.stringContaining('merge_from_dashboard') })
  })
})

// 2026-10-28: Approve on PRs #600 and #739 was refused in 3 s with "the build machine or the project's test setup
// failed", while the gate's own reason ("1.6 GB free, the gate needs 5.0 GB") was dropped. A GATE_INFRA refusal now
// says which part of the machine failed, in words the owner can act on; the code stays GATE_INFRA.
describe('infraCause: a machine failure names its cause', () => {
  const DISK = 'Disk check before rebasing onto main:\n\nNo space left on device for the check: 1.6 GB free, the gate needs 5.0 GB. Free up space on this Mac, then approve again.'
  const GENERIC = /build machine or the project's test setup failed/i

  it('names a nearly full disk with both numbers and the machine', () => {
    const c = infraCause(DISK, { where: 'Mac mini' })
    expect(c.cause).toBe("The Mac mini's disk is nearly full (1.6 GB free, the check needs 5.0 GB)")
    expect(c.next).toMatch(/free up space/i)
  })

  it('says "This Mac" when the machine is unknown, and never a blank name', () => {
    for (const where of [undefined, null, '', '   ']) {
      expect(infraCause(DISK, { where }).cause).toMatch(/^This Mac's disk is nearly full/)
    }
  })

  it('the disk check wins over the plain "no space left on device" it also contains', () => {
    expect(infraCause(DISK).cause).toMatch(/nearly full \(1\.6 GB free/)
  })

  it('says first aid already ran when it did, so the owner knows clearing was tried', () => {
    const c = infraCause(`${DISK}\n\nFirst aid ran first: freed 300 MiB (aerial videos 300 MiB, caches 0 MiB); 1.9 GB free after.`, { where: 'Mac mini' })
    expect(c.cause).toContain('1.6 GB free')
    expect(c.next).toMatch(/cleared rebuildable files first \(freed 300 MiB \(aerial videos 300 MiB, caches 0 MiB\); 1\.9 GB free after\), and it was not enough/)
  })

  it.each([
    ['Tests failed after rebasing onto main:\n\nERROR: [Errno 28] No space left on device', /disk filled up/i],
    ['Tests failed after rebasing onto main:\n\nFinanceOS unit tests (npm test) cannot run: this project has no test command yet', /no test command/i],
    ['Tests failed after rebasing onto main:\n\nnpm error Missing script: "test"', /no test command/i],
    ['Tests failed after rebasing onto main:\n\nerror: unable to attach DB: accessing build database: database is locked', /same build database at once/i],
    ['Tests failed after rebasing onto main:\n\nfatal: unable to access: Could not resolve host: github.com', /lost its network/i],
    ['Tests failed after rebasing onto main:\n\nPermissionError: [Errno 1] Operation not permitted: x', /privacy permission/i],
    ['Tests failed after rebasing onto main:\n\nOSError: [Errno 24] Too many open files', /open files/i],
    ['Tests failed after rebasing onto main:\n\nfork: Resource temporarily unavailable', /processes/i],
    ['Tests failed after rebasing onto main:\n\nCannot allocate memory', /out of memory/i]
  ])('names the cause of %s', (reason, expected) => {
    const c = infraCause(reason, { where: 'Mac mini' })
    expect(c.cause).toMatch(expected)
    expect(c.cause).not.toMatch(GENERIC)
    expect(summarizeGateFailure(reason).code).toBe('GATE_INFRA') // the code is unchanged
  })

  it('is null for failures that are the code\'s, so a real test failure is never relabelled', () => {
    expect(infraCause('Tests failed after rebasing onto main:\n\nFAILED lib/tests/test_a.py::test_one')).toBeNull()
    expect(infraCause('Rebase onto main failed:\n\nCONFLICT (content)')).toBeNull()
    expect(infraCause('')).toBeNull()
    expect(infraCause(null)).toBeNull()
    expect(infraCause(undefined)).toBeNull()
  })

  it('stays one short line whatever the output or the machine label holds', () => {
    const where = 'evil\nname <script>alert(1)</script>' + 'x'.repeat(500)
    const c = infraCause(`${'noise\n'.repeat(5000)}database is locked\n${'y'.repeat(10000)}`, { where })
    expect(c.cause).not.toContain('\n')
    expect(c.cause.length).toBeLessThanOrEqual(200)
    const d = infraCause(DISK, { where })
    expect(d.cause).not.toContain('\n')
    expect(d.cause.length).toBeLessThanOrEqual(200)
  })

  it('does not trust numbers that are not the disk check\'s own wording', () => {
    // A test that prints "5 GB free" is not the gate's disk check; it must not read as a full disk.
    const c = infraCause('Tests failed after rebasing onto main:\n\nNo space left on device; test printed: 5.0 GB free, the gate needs 9.0 GB')
    expect(c.cause).toMatch(/disk filled up/i)
    expect(c.cause).not.toContain('5.0 GB')
  })

  it('summarizeGateFailure carries the cause for GATE_INFRA and none otherwise', () => {
    const s = summarizeGateFailure(DISK, { where: 'Mac mini' })
    expect(s.code).toBe('GATE_INFRA')
    expect(s.cause).toBe("The Mac mini's disk is nearly full (1.6 GB free, the check needs 5.0 GB)")
    expect(summarizeGateFailure('Tests failed after rebasing onto main:\n\nFAILED a::b').cause).toBeNull()
  })
})
