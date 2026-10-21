import { describe, it, expect } from 'vitest'
import { checkRuns, ciState } from '../webhook-server/ci_status.js'

// marvin#555: each check's own state and times, for MR Review's "2 of 3 done" bar and its per-check drill-down.
const run = (name, status, conclusion, startedAt, completedAt, workflowName = 'CI') => ({ __typename: 'CheckRun', name, status, conclusion, startedAt, completedAt, workflowName })
const ctx = (context, state, extra = {}) => ({ __typename: 'StatusContext', context, state, ...extra })

describe('checkRuns: one row per check, in GitHub order', () => {
  it('no rollup, an empty one, or junk entries: no rows, never a throw', () => {
    expect(checkRuns(null)).toEqual([])
    expect(checkRuns(undefined)).toEqual([])
    expect(checkRuns([])).toEqual([])
    expect(checkRuns('not a list')).toEqual([])
    expect(checkRuns([null, 7, 'x'])).toEqual([])
  })

  it('names the state plainly and keeps the times GitHub gave', () => {
    const rows = checkRuns([
      run('Website checks', 'COMPLETED', 'SUCCESS', '2026-10-21T05:58:02Z', '2026-10-21T05:58:50Z'),
      run('App builds (iOS)', 'IN_PROGRESS', '', '2026-10-21T05:58:02Z', null),
      run('Lint', 'QUEUED', null, null, null)
    ])
    expect(rows).toEqual([
      { name: 'Website checks', status: 'passed', done: true, startedAt: '2026-10-21T05:58:02Z', completedAt: '2026-10-21T05:58:50Z' },
      { name: 'App builds (iOS)', status: 'running', done: false, startedAt: '2026-10-21T05:58:02Z', completedAt: null },
      { name: 'Lint', status: 'queued', done: false, startedAt: null, completedAt: null }
    ])
  })

  it('every finished conclusion counts as done, failed or not', () => {
    const states = ['SUCCESS', 'FAILURE', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE', 'SKIPPED', 'NEUTRAL', 'STALE', null]
      .map((c) => checkRuns([run('x', 'COMPLETED', c)])[0])
    expect(states.every((r) => r.done)).toBe(true)
    expect(states.map((r) => r.status)).toEqual(['passed', 'failed', 'failed', 'failed', 'failed', 'failed', 'skipped', 'neutral', 'neutral', 'neutral'])
  })

  it('waiting, pending, requested and unknown statuses are queued, not running', () => {
    for (const s of ['WAITING', 'PENDING', 'REQUESTED', 'QUEUED', undefined, 'SOMETHING_NEW']) {
      expect(checkRuns([run('x', s, null)])[0]).toMatchObject({ status: 'queued', done: false })
    }
  })

  it('commit statuses (the older kind): success/failure/error are done; pending runs; expected has not started', () => {
    const rows = checkRuns([ctx('ci/a', 'SUCCESS', { startedAt: '2026-10-21T06:00:00Z' }), ctx('ci/b', 'ERROR'), ctx('ci/c', 'PENDING', { createdAt: '2026-10-21T06:01:00Z' }), ctx('ci/d', 'EXPECTED')])
    expect(rows.map((r) => [r.name, r.status, r.done])).toEqual([['ci/a', 'passed', true], ['ci/b', 'failed', true], ['ci/c', 'running', false], ['ci/d', 'queued', false]])
    expect(rows[2].startedAt).toBe('2026-10-21T06:01:00Z') // a status has no startedAt of its own: when it was posted
    expect(rows[0].completedAt).toBe(null) // and no finish time, so no duration is ever invented
  })

  it('a re-run check shows once, as its newest run, not as an old failure beside a new run', () => {
    const rows = checkRuns([
      run('tests', 'COMPLETED', 'FAILURE', '2026-10-21T05:00:00Z', '2026-10-21T05:03:00Z'),
      run('tests', 'IN_PROGRESS', null, '2026-10-21T05:10:00Z', null)
    ])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ status: 'running', startedAt: '2026-10-21T05:10:00Z' })
    // listed newest-first, the newest still wins
    expect(checkRuns([run('t', 'IN_PROGRESS', null, '2026-10-21T05:10:00Z'), run('t', 'COMPLETED', 'FAILURE', '2026-10-21T05:00:00Z', '2026-10-21T05:03:00Z')])[0].status).toBe('running')
    // a re-run queued again has no start time yet: it is still newer than the finished one
    expect(checkRuns([run('t', 'COMPLETED', 'FAILURE', '2026-10-21T05:00:00Z', '2026-10-21T05:03:00Z'), run('t', 'QUEUED', null, null)])[0].status).toBe('queued')
  })

  it('the same job name in two workflows is two checks', () => {
    expect(checkRuns([run('test', 'COMPLETED', 'SUCCESS', null, null, 'iOS'), run('test', 'IN_PROGRESS', null, null, null, 'site')])).toHaveLength(2)
  })

  it('a check without a name still gets a row', () => {
    expect(checkRuns([{ __typename: 'CheckRun', status: 'IN_PROGRESS' }, { __typename: 'StatusContext', state: 'PENDING' }]).map((r) => r.name)).toEqual(['check', 'status'])
  })

  it('twelve checks keep their order and all twelve rows', () => {
    const many = Array.from({ length: 12 }, (_, i) => run(`job ${i}`, i < 5 ? 'COMPLETED' : 'IN_PROGRESS', i < 5 ? 'SUCCESS' : null))
    expect(checkRuns(many).map((r) => r.name)).toEqual(many.map((r) => r.name))
  })

  it('does not change what ciState decides (the merge gate reads that)', () => {
    const rollup = [run('a', 'COMPLETED', 'SUCCESS'), run('b', 'IN_PROGRESS', null)]
    checkRuns(rollup)
    expect(ciState(rollup)).toEqual({ state: 'pending', failing: [], pending: ['b'] })
  })
})
