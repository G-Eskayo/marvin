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
