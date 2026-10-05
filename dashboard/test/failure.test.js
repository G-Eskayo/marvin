import { describe, it, expect, vi } from 'vitest'
import {
  classifyFailure,
  summarizeGateFailure,
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
