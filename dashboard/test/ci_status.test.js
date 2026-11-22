import { describe, it, expect, vi } from 'vitest'
import { ciState, assertChecksGreen, waitForRequiredChecks } from '../webhook-server/ci_status.js'
import { MergeFailure } from '../webhook-server/failure.js'

const run = (name, status, conclusion) => ({ __typename: 'CheckRun', name, status, conclusion })
const ctx = (name, state) => ({ __typename: 'StatusContext', context: name, state })

describe('ciState: what GitHub says about a PR\'s checks', () => {
  it('no checks at all (a repo without CI) is "none", never a block', () => {
    expect(ciState(null)).toEqual({ state: 'none', failing: [], pending: [] })
    expect(ciState([])).toEqual({ state: 'none', failing: [], pending: [] })
  })
  it('all completed and successful (skipped and neutral count as fine) is passing', () => {
    expect(ciState([run('a', 'COMPLETED', 'SUCCESS'), run('b', 'COMPLETED', 'SKIPPED'), run('c', 'COMPLETED', 'NEUTRAL'), ctx('d', 'SUCCESS')]).state).toBe('passing')
  })
  it('failure-like conclusions (not infrastructure issues) fail it, and names which checks', () => {
    for (const c of ['FAILURE', 'ACTION_REQUIRED', 'STARTUP_FAILURE']) {
      expect(ciState([run('swift', 'COMPLETED', c), run('ok', 'COMPLETED', 'SUCCESS')])).toMatchObject({ state: 'failing', failing: ['swift'] })
    }
    expect(ciState([ctx('legacy', 'FAILURE')])).toMatchObject({ state: 'failing', failing: ['legacy'] })
    expect(ciState([ctx('legacy', 'ERROR')]).state).toBe('failing')
  })
  it('infrastructure issues (TIMED_OUT, CANCELLED) never count as failing', () => {
    for (const c of ['TIMED_OUT', 'CANCELLED']) {
      expect(ciState([run('infra', 'COMPLETED', c), run('ok', 'COMPLETED', 'SUCCESS')]).state).toBe('passing')
    }
  })
  it('anything still queued or running is pending, and names it', () => {
    expect(ciState([run('build', 'IN_PROGRESS', null), run('ok', 'COMPLETED', 'SUCCESS')])).toMatchObject({ state: 'pending', pending: ['build'] })
    expect(ciState([run('q', 'QUEUED', null)]).state).toBe('pending')
    expect(ciState([ctx('legacy', 'PENDING')]).state).toBe('pending')
  })
  it('a failure outranks pending: no point waiting for the rest', () => {
    expect(ciState([run('a', 'COMPLETED', 'FAILURE'), run('b', 'IN_PROGRESS', null)]).state).toBe('failing')
  })
})

describe('assertChecksGreen', () => {
  const PR = 'https://github.com/G-Eskayo/clarity-captions/pull/57'
  const viewing = (rollup) => vi.fn().mockResolvedValue({ stdout: JSON.stringify({ statusCheckRollup: rollup }) })

  it('passes for passing checks and for a repo with none', async () => {
    await expect(assertChecksGreen(PR, viewing([run('a', 'COMPLETED', 'SUCCESS')]))).resolves.toBeUndefined()
    await expect(assertChecksGreen(PR, viewing([]))).resolves.toBeUndefined()
  })
  it('failing checks send the PR back: it is the code that is wrong', async () => {
    await expect(assertChecksGreen(PR, viewing([run('CaptionCore unit tests', 'COMPLETED', 'FAILURE')]))).rejects.toMatchObject({
      payload: { code: 'CI_FAILED', action: 'reengage', message: expect.stringContaining('CaptionCore unit tests') }
    })
  })
  it('running checks refuse without sending it back: just wait', async () => {
    await expect(assertChecksGreen(PR, viewing([run('build', 'IN_PROGRESS', null)]))).rejects.toMatchObject({
      payload: { code: 'CI_PENDING', action: 'escalate', message: expect.stringContaining('build') }
    })
    await expect(assertChecksGreen(PR, viewing([run('build', 'IN_PROGRESS', null)]))).rejects.toBeInstanceOf(MergeFailure)
  })
  it('does not block on a metadata hiccup', async () => {
    await expect(assertChecksGreen(PR, vi.fn().mockRejectedValue(new Error('boom')))).resolves.toBeUndefined()
    await expect(assertChecksGreen(PR, vi.fn().mockResolvedValue({ stdout: 'not json' }))).resolves.toBeUndefined()
  })
})

// marvin#1099: the merge gate is the check. GitHub's copy of a check the gate runs itself doesn't block; a check the
// gate doesn't run (the secret scan) still does.
describe('ciState with checks the gate covers', () => {
  const GATE = ['Rules', 'Python tests', 'Dashboard unit tests']
  it('a cancelled, failed or pending Python job no longer blocks when the gate runs Python itself', () => {
    for (const c of [run('Python tests', 'COMPLETED', 'CANCELLED'), run('Python tests', 'COMPLETED', 'FAILURE'), run('Python tests', 'QUEUED', null)]) {
      expect(ciState([c, run('Secret and transcript scan', 'COMPLETED', 'SUCCESS')], { ignore: GATE }).state).toBe('passing')
    }
  })
  it('a check the gate does not run still blocks', () => {
    expect(ciState([run('Secret and transcript scan', 'COMPLETED', 'FAILURE'), run('Python tests', 'COMPLETED', 'SUCCESS')], { ignore: GATE }))
      .toMatchObject({ state: 'failing', failing: ['Secret and transcript scan'] })
    expect(ciState([run('Secret and transcript scan', 'IN_PROGRESS', null)], { ignore: GATE }).state).toBe('pending')
  })
  it('commit statuses are matched by their context name too', () => {
    expect(ciState([ctx('Python tests', 'FAILURE')], { ignore: GATE }).state).toBe('none')
    expect(ciState([ctx('other', 'FAILURE')], { ignore: GATE }).state).toBe('failing')
  })
  it('only ignored checks present reads as none (nothing GitHub-only to wait for)', () => {
    expect(ciState([run('Python tests', 'COMPLETED', 'CANCELLED')], { ignore: GATE })).toEqual({ state: 'none', failing: [], pending: [] })
  })
  it('CANCELLED and TIMED_OUT are infrastructure issues, never count as failing', () => {
    // CANCELLED/TIMED_OUT are runner issues, not code failures, so they never count as failing or pending
    expect(ciState([run('Python tests', 'COMPLETED', 'CANCELLED')]).state).toBe('passing')
    expect(ciState([run('Python tests', 'COMPLETED', 'TIMED_OUT')]).state).toBe('passing')
    expect(ciState([run('ok', 'COMPLETED', 'SUCCESS'), run('cancelled', 'COMPLETED', 'CANCELLED')]).state).toBe('passing')
    // A FAILURE still fails even if there are CANCELLED checks
    expect(ciState([run('failed', 'COMPLETED', 'FAILURE'), run('cancelled', 'COMPLETED', 'CANCELLED')]).state).toBe('failing')
  })
  it('names must match exactly: a similar name is not covered', () => {
    expect(ciState([run('Python tests (slow)', 'COMPLETED', 'FAILURE')], { ignore: GATE }).state).toBe('failing')
  })
})

describe('assertChecksGreen with checks the gate covers', () => {
  const answer = (rollup) => vi.fn(async () => ({ stdout: JSON.stringify({ statusCheckRollup: rollup }) }))
  it('does not refuse a PR whose only red check is one the gate runs', async () => {
    await expect(assertChecksGreen('https://github.com/o/r/pull/1', answer([run('Python tests', 'COMPLETED', 'CANCELLED')]), { ignore: ['Python tests'] })).resolves.toBeUndefined()
  })
  it('still sends back a PR whose GitHub-only check failed', async () => {
    await expect(assertChecksGreen('https://github.com/o/r/pull/1', answer([run('Secret and transcript scan', 'COMPLETED', 'FAILURE')]), { ignore: ['Python tests'] }))
      .rejects.toMatchObject({ payload: { code: 'CI_FAILED' } })
  })
})

describe('gateCheckNames and postGateStatus (marvin#1099)', async () => {
  const fs = await import('fs')
  const os = await import('os')
  const path = await import('path')
  const { gateCheckNames, postGateStatus } = await import('../webhook-server/ci_status.js')
  const dirWith = (text) => {
    const d = fs.mkdtempSync(path.join(os.tmpdir(), 'gate-'))
    fs.mkdirSync(path.join(d, '.github'))
    if (text !== null) fs.writeFileSync(path.join(d, '.github', 'required-checks.json'), text)
    return d
  }
  it('names the checks the gate runs and leaves out the CI-only ones', () => {
    const d = dirWith(JSON.stringify({ checks: [{ id: 'python', name: 'Python tests' }, { id: 'rules', name: 'Rules', where: 'both' },
      { id: 'secret-scan', name: 'Secret and transcript scan', where: 'ci' }] }))
    expect(gateCheckNames(d)).toEqual(['Python tests', 'Rules'])
  })
  it('a missing, broken or odd list covers nothing', () => {
    for (const t of [null, '{not json', '{"checks": "x"}', '{"checks": [{"id": 1}]}']) expect(gateCheckNames(dirWith(t))).toEqual([])
  })
  it("this repo's own list covers every required check, the secret scan too (#1101): no merge waits on GitHub", () => {
    const names = gateCheckNames(path.resolve(import.meta.dirname, '..', '..'))
    expect(names).toEqual(expect.arrayContaining(['Python tests', 'Rules', 'Dashboard unit tests', 'Secret and transcript scan']))
  })
  it('posts a MARVIN gate success on the PR head', async () => {
    const calls = []
    const exec = async (cmd, args) => { calls.push(args); return { stdout: args[1] === 'view' ? 'a'.repeat(40) : '' } }
    expect(await postGateStatus('https://github.com/G-Eskayo/marvin/pull/1093', exec, ['Python tests'])).toBe(true)
    expect(calls[1]).toEqual(expect.arrayContaining(['api', `repos/G-Eskayo/marvin/statuses/${'a'.repeat(40)}`, 'state=success', 'context=MARVIN gate']))
  })
  it('a failed post, an odd head or a non-PR url never throws', async () => {
    expect(await postGateStatus('https://github.com/o/r/pull/1', async () => { throw new Error('403') })).toBe(false)
    expect(await postGateStatus('https://github.com/o/r/pull/1', async () => ({ stdout: 'not-a-sha' }))).toBe(false)
    expect(await postGateStatus('not a url', async () => ({ stdout: '' }))).toBe(false)
  })
})

describe('waitForRequiredChecks (marvin#868)', () => {
  const PR = 'https://github.com/G-Eskayo/marvin/pull/1'
  const viewData = (rollup, oid = 'a'.repeat(40)) => ({ headRefOid: oid, statusCheckRollup: rollup })
  const exec = (data, ...more) => {
    const history = Array.isArray(data) ? data : [data, ...more]
    let call = 0
    return vi.fn(async () => {
      const result = history[Math.min(call, history.length - 1)]
      call++
      if (result instanceof Error) throw result
      return { stdout: JSON.stringify(result) }
    })
  }

  it('1: all required checks already SUCCESS → resolves {ok:true} immediately, sleep never called', async () => {
    const sleepFn = vi.fn()
    const e = exec(viewData([run('a', 'COMPLETED', 'SUCCESS'), run('b', 'COMPLETED', 'SUCCESS')]))
    const result = await waitForRequiredChecks(PR, ['a', 'b'], e, { sleep: sleepFn, timeoutMs: 100_000 })
    expect(result).toEqual({ ok: true })
    expect(sleepFn).not.toHaveBeenCalled()
    expect(e).toHaveBeenCalledOnce()
  })

  it('2: one required check FAILURE → {ok:false, code:\'CI_FAILED\', names}', async () => {
    const e = exec(viewData([run('failed', 'COMPLETED', 'FAILURE'), run('ok', 'COMPLETED', 'SUCCESS')]))
    const result = await waitForRequiredChecks(PR, ['failed', 'ok'], e, { timeoutMs: 100_000 })
    expect(result).toEqual({ ok: false, code: 'CI_FAILED', names: ['failed'], reason: expect.stringContaining('failed') })
  })

  it('3: one required check CANCELLED → returns CI_TIMEOUT immediately (infrastructure issue, not code)', async () => {
    const sleepFn = vi.fn()
    const e = exec(viewData([run('cancelled', 'COMPLETED', 'CANCELLED')]))
    const result = await waitForRequiredChecks(PR, ['cancelled'], e, { sleep: sleepFn, timeoutMs: 60_000 })
    expect(result).toEqual({ ok: false, code: 'CI_TIMEOUT', names: ['cancelled'], reason: expect.stringContaining('cancelled') })
    expect(sleepFn).not.toHaveBeenCalled()
  })

  it('4: required check QUEUED on poll 1, SUCCESS on poll 2 → waits it out, resolves {ok:true}', async () => {
    const sleepFn = vi.fn().mockResolvedValue(undefined)
    const e = exec(
      viewData([run('a', 'QUEUED', null)]),
      viewData([run('a', 'COMPLETED', 'SUCCESS')])
    )
    const result = await waitForRequiredChecks(PR, ['a'], e, { sleep: sleepFn, timeoutMs: 100_000 })
    expect(result).toEqual({ ok: true })
    expect(sleepFn).toHaveBeenCalledOnce()
  })

  it('5: required name never appears in rollup → counted as pending, times out to CI_TIMEOUT', async () => {
    let time = 0
    const now = () => time
    const sleepFn = vi.fn(async () => { time += 15_000 })
    const e = exec(viewData([run('other', 'COMPLETED', 'SUCCESS')]))
    const result = await waitForRequiredChecks(PR, ['missing'], e, { sleep: sleepFn, now, timeoutMs: 60_000 })
    expect(result).toEqual({ ok: false, code: 'CI_TIMEOUT', names: ['missing'], reason: expect.stringContaining('did not finish') })
    expect(e.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('6: exec throws or unparseable JSON on some polls → keeps polling, resolves once a later poll succeeds', async () => {
    const sleepFn = vi.fn().mockResolvedValue(undefined)
    const e = exec(
      new Error('403'),
      new Error('timeout'),
      viewData([run('a', 'COMPLETED', 'SUCCESS')])
    )
    const result = await waitForRequiredChecks(PR, ['a'], e, { sleep: sleepFn, timeoutMs: 100_000 })
    expect(result).toEqual({ ok: true })
    expect(e).toHaveBeenCalledTimes(3)
    expect(sleepFn.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('7: exec always throws/unparseable → bounded by timeout, ends in CI_TIMEOUT, never hangs', async () => {
    let time = 0
    const now = () => time
    const sleepFn = vi.fn(async () => { time += 20_000 })
    const e = exec(new Error('always fails'))
    const result = await waitForRequiredChecks(PR, ['a'], e, { sleep: sleepFn, now, timeoutMs: 60_000 })
    expect(result).toEqual({ ok: false, code: 'CI_TIMEOUT', names: ['a'], reason: expect.stringContaining('did not finish') })
    expect(e.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('8: headRefOid changes between polls (branch pushed while waiting) → CI_HEAD_MOVED, escalates', async () => {
    const sleepFn = vi.fn().mockResolvedValue(undefined)
    const e = exec(
      viewData([run('a', 'IN_PROGRESS', null)], 'old'),
      viewData([run('a', 'IN_PROGRESS', null)], 'new')
    )
    const result = await waitForRequiredChecks(PR, ['a'], e, { sleep: sleepFn, timeoutMs: 100_000, targetOid: 'old' })
    expect(result).toEqual({ ok: false, code: 'CI_HEAD_MOVED', names: [], reason: expect.stringContaining('pushed to') })
    expect(sleepFn).toHaveBeenCalledOnce()
  })

  it('9: empty/absent names → {ok:true} without calling exec', async () => {
    const e = vi.fn()
    expect(await waitForRequiredChecks(PR, [], e, { timeoutMs: 100_000 })).toEqual({ ok: true })
    expect(await waitForRequiredChecks(PR, null, e, { timeoutMs: 100_000 })).toEqual({ ok: true })
    expect(e).not.toHaveBeenCalled()
  })

  it('10: SKIPPED/NEUTRAL conclusion on required check counts as satisfied', async () => {
    const sleepFn = vi.fn()
    const e = exec(viewData([run('a', 'COMPLETED', 'SKIPPED'), run('b', 'COMPLETED', 'NEUTRAL')]))
    const result = await waitForRequiredChecks(PR, ['a', 'b'], e, { sleep: sleepFn, timeoutMs: 100_000 })
    expect(result).toEqual({ ok: true })
    expect(sleepFn).not.toHaveBeenCalled()
  })

  it('11: a failing check not in the required names list is ignored', async () => {
    const sleepFn = vi.fn()
    const e = exec(viewData([run('required', 'COMPLETED', 'SUCCESS'), run('other', 'COMPLETED', 'FAILURE')]))
    const result = await waitForRequiredChecks(PR, ['required'], e, { sleep: sleepFn, timeoutMs: 100_000 })
    expect(result).toEqual({ ok: true })
    expect(sleepFn).not.toHaveBeenCalled()
  })
})
