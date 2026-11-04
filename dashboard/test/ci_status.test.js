import { describe, it, expect, vi } from 'vitest'
import { ciState, assertChecksGreen } from '../webhook-server/ci_status.js'
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
  it('any failure-like conclusion fails it, and names which checks', () => {
    for (const c of ['FAILURE', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE']) {
      expect(ciState([run('swift', 'COMPLETED', c), run('ok', 'COMPLETED', 'SUCCESS')])).toMatchObject({ state: 'failing', failing: ['swift'] })
    }
    expect(ciState([ctx('legacy', 'FAILURE')])).toMatchObject({ state: 'failing', failing: ['legacy'] })
    expect(ciState([ctx('legacy', 'ERROR')]).state).toBe('failing')
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
  it('with no ignore list the behaviour is exactly as before', () => {
    expect(ciState([run('Python tests', 'COMPLETED', 'CANCELLED')]).state).toBe('failing')
    expect(ciState([run('Python tests', 'COMPLETED', 'CANCELLED')], {}).state).toBe('failing')
    expect(ciState([run('Python tests', 'COMPLETED', 'CANCELLED')], { ignore: null }).state).toBe('failing')
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
