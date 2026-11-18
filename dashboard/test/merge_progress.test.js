import { describe, it, expect, vi } from 'vitest'
import { MERGE_STAGES, emptyProgress, applyMergeEvent, mergeRuns, closeRunning, machineLabel, estimateLine, busyLine, opForHead } from '../src/lib/merge_progress.js'
import { createMergeJoin } from '../webhook-server/merge_progress.js'

// marvin#568: the merge's stage events, pushed from the webhook, folded into one progress object. The same reducer runs
// in the webhook (its own record), the main process (what a card reads on mount) and so the card sees what both saw.
const T0 = Date.parse('2026-10-21T19:00:00Z')
const ev = (seq, stage, state, extra = {}) => ({ id: 'm1', seq, stage, state, at: T0 + seq * 1000, ...extra })
const fold = (events, p = emptyProgress()) => events.reduce(applyMergeEvent, p)
const states = (p) => Object.fromEntries(MERGE_STAGES.map(([k]) => [k, p.stages[k]?.state || 'waiting']))

describe('applyMergeEvent', () => {
  it('the stages are the ticket\'s eight, in order', () => {
    expect(MERGE_STAGES.map(([, label]) => label)).toEqual(['Queued', 'Fetching PR', 'Rebasing on main', 'Installing', 'Tests', 'Merging on GitHub', 'After-merge checks', 'Done'])
  })

  it('in-order events: each stage running then done, the earlier ones closed', () => {
    const p = fold([ev(1, 'queued', 'running'), ev(2, 'fetching', 'running'), ev(3, 'rebasing', 'running'), ev(4, 'installing', 'running'), ev(5, 'tests', 'running')])
    expect(states(p)).toMatchObject({ queued: 'done', fetching: 'done', rebasing: 'done', installing: 'done', tests: 'running', merging: 'waiting' })
    expect(p.stages.queued).toMatchObject({ startedAt: T0 + 1000, endedAt: T0 + 2000 })
    expect(p.id).toBe('m1')
    expect(p.seq).toBe(5)
  })

  it('a duplicate event (the stream and the local ping both deliver it) changes nothing', () => {
    const p = fold([ev(1, 'queued', 'running'), ev(2, 'fetching', 'running')])
    expect(applyMergeEvent(p, ev(2, 'fetching', 'running'))).toBe(p)
  })

  it('a late event (lower seq, arriving after a newer one) is ignored, and the picture stays consistent', () => {
    const p = fold([ev(1, 'queued', 'running'), ev(3, 'rebasing', 'running')])
    // fetching (seq 2) never arrived before rebasing; it was closed by rebasing starting, not left "running" forever.
    expect(states(p)).toMatchObject({ queued: 'done', fetching: 'skipped', rebasing: 'running' })
    const late = applyMergeEvent(p, ev(2, 'fetching', 'running'))
    expect(late).toBe(p)
  })

  it('an event from another merge attempt (a different id) is ignored', () => {
    const p = fold([ev(1, 'queued', 'running'), ev(2, 'fetching', 'running')])
    expect(applyMergeEvent(p, { ...ev(9, 'merging', 'running'), id: 'older' })).toBe(p)
  })

  it('skipped stages (no retest needed) read as skipped, not done', () => {
    const p = fold([ev(1, 'fetching', 'running'), ev(2, 'rebasing', 'skipped', { detail: 'main changed none of its files' }), ev(3, 'installing', 'skipped'), ev(4, 'tests', 'skipped'), ev(5, 'merging', 'running')])
    expect(states(p)).toMatchObject({ fetching: 'done', rebasing: 'skipped', installing: 'skipped', tests: 'skipped', merging: 'running' })
    expect(p.stages.rebasing.detail).toBe('main changed none of its files')
  })

  it('a live test count updates the Tests row without restarting it', () => {
    const p = fold([ev(1, 'tests', 'running', { detail: 'Python' }), ev(2, 'tests', 'running', { count: { done: 40, total: 100, unit: '%' } }), ev(3, 'tests', 'running', { count: { done: 120, total: 183, unit: 'files' }, detail: 'Dashboard' })])
    expect(p.stages.tests).toMatchObject({ state: 'running', startedAt: T0 + 1000, count: { done: 120, total: 183, unit: 'files' }, detail: 'Dashboard' })
  })

  it('a failed stage stays failed; nothing after it runs', () => {
    const p = fold([ev(1, 'tests', 'running'), ev(2, 'tests', 'failed', { detail: 'GATE_INFRA: cut off' })])
    expect(p.stages.tests).toMatchObject({ state: 'failed', detail: 'GATE_INFRA: cut off', endedAt: T0 + 2000 })
    expect(p.outcome).toBe('failed')
    expect(applyMergeEvent(p, ev(3, 'tests', 'running'))).toBe(p)
  })

  it('done ends it: outcome merged', () => {
    const p = fold([ev(1, 'merging', 'running'), ev(2, 'after', 'running'), ev(3, 'done', 'done')])
    expect(p.outcome).toBe('merged')
    expect(states(p)).toMatchObject({ merging: 'done', after: 'done', done: 'done' })
  })

  it('machine and estimate ride on any event and are kept', () => {
    const p = fold([ev(1, 'fetching', 'running', { machine: { id: 'mac-mini-1', busy: true, load: 9.2, cores: 10, top: 'engine test' } }), ev(2, 'rebasing', 'running', { estimateMs: 180_000 })])
    expect(p.machine).toMatchObject({ id: 'mac-mini-1', busy: true })
    expect(p.estimateMs).toBe(180_000)
  })

  it('junk never throws and never changes the progress', () => {
    const p = fold([ev(1, 'queued', 'running')])
    for (const bad of [null, undefined, 'x', 42, {}, { seq: 'a' }, ev(5, 'nope', 'running'), ev(5, 'tests', 'exploded'), { ...ev(5, 'tests', 'running'), seq: NaN }]) {
      expect(applyMergeEvent(p, bad)).toBe(p)
    }
    expect(applyMergeEvent(null, ev(1, 'queued', 'running')).stages.queued.state).toBe('running')
  })

  it('an oversized detail is cut, so a test output wall cannot ride along', () => {
    const p = fold([ev(1, 'tests', 'failed', { detail: 'x'.repeat(50_000) })])
    expect(p.stages.tests.detail.length).toBeLessThanOrEqual(300)
  })
})

describe('mergeRuns: the rows #557\'s CheckProgress draws', () => {
  it('one row per stage, with waiting/running/done/failed/skipped words and the check icons', () => {
    const p = fold([ev(1, 'queued', 'running'), ev(2, 'fetching', 'running'), ev(3, 'rebasing', 'skipped'), ev(5, 'tests', 'running', { count: { done: 120, total: 183, unit: 'files' }, detail: 'Dashboard' })])
    const runs = mergeRuns(p)
    expect(runs.map((r) => r.name)).toEqual(['Queued', 'Fetching PR', 'Rebasing on main', 'Installing', 'Tests · Dashboard 120/183', 'Merging on GitHub', 'After-merge checks', 'Done'])
    expect(runs.map((r) => r.label)).toEqual(['done', 'done', 'skipped', 'skipped', 'running', 'waiting', 'waiting', 'waiting'])
    expect(runs.map((r) => r.status)).toEqual(['passed', 'passed', 'skipped', 'skipped', 'running', 'queued', 'queued', 'queued'])
    expect(runs[4]).toMatchObject({ done: false, waiting: false, startedAt: T0 + 5000 })
    expect(runs[5]).toMatchObject({ done: false, waiting: true })
    expect(runs[0]).toMatchObject({ done: true, startedAt: T0 + 1000, completedAt: T0 + 2000 })
  })

  it('a running Queued says how many merges are ahead', () => {
    expect(mergeRuns(fold([ev(1, 'queued', 'running', { detail: '1 merge ahead' })]))[0].name).toBe('Queued · 1 merge ahead')
    expect(mergeRuns(fold([ev(1, 'queued', 'running', { detail: '1 merge ahead' }), ev(2, 'fetching', 'running')]))[0].name).toBe('Queued')
  })

  it('a percent count reads as a percent', () => {
    const p = fold([ev(1, 'tests', 'running', { count: { done: 42, total: 100, unit: '%' }, detail: 'Python' })])
    expect(mergeRuns(p)[4].name).toBe('Tests · Python 42%')
  })

  it('no progress yet: every stage waiting', () => {
    expect(mergeRuns(null).every((r) => r.label === 'waiting')).toBe(true)
  })
})

describe('the lines under the bar', () => {
  it('machine names read like the owner says them', () => {
    expect(machineLabel('mac-mini-1')).toBe('Mac mini')
    expect(machineLabel('macbook-pro-1')).toBe('MacBook Pro')
    expect(machineLabel('mac-mini-2012')).toBe('Mac mini 2012')
    expect(machineLabel(null)).toBe('the merge machine')
    expect(machineLabel('<img src=x>')).toBe('<img src=x>') // rendered as text by React, never as HTML
  })

  it('estimate from real past durations, and on which machine', () => {
    expect(estimateLine({ estimateMs: 185_000, machine: { id: 'mac-mini-1' } })).toBe('Usually about 3 min · on Mac mini')
    expect(estimateLine({ estimateMs: 20_000, machine: { id: 'mac-mini-1' } })).toBe('Usually under a minute · on Mac mini')
    expect(estimateLine({ estimateMs: null, machine: { id: 'mac-mini-1' } })).toBe('On Mac mini')
    expect(estimateLine({ estimateMs: 0 })).toBe(null)
    expect(estimateLine(null)).toBe(null)
  })

  it('a plain warning only when the machine is busy', () => {
    expect(busyLine({ machine: { id: 'mac-mini-1', busy: true, top: 'engine test' } })).toBe('Mac mini is busy (engine test running); this may be slow')
    expect(busyLine({ machine: { id: 'mac-mini-1', busy: true, load: 9.2, cores: 10 } })).toBe('Mac mini is busy (load 9.2 on 10 cores); this may be slow')
    expect(busyLine({ machine: { id: 'mac-mini-1', busy: false } })).toBe(null)
    expect(busyLine({})).toBe(null)
  })
})

describe('opForHead (#567: a finished attempt belongs to the commit it ran on)', () => {
  it('an older head reads idle; a running merge or an unknown head never hides', () => {
    expect(opForHead({ state: 'error', head: 'a' }, 'b')).toEqual({ state: 'idle' })
    expect(opForHead({ state: 'interrupted', head: 'a' }, 'b')).toEqual({ state: 'idle' })
    expect(opForHead({ state: 'error', head: 'a' }, 'a').state).toBe('error')
    expect(opForHead({ state: 'error', head: null }, 'b').state).toBe('error')
    expect(opForHead({ state: 'merging', head: 'a' }, 'b').state).toBe('merging')
    expect(opForHead(null, 'b')).toEqual({ state: 'idle' })
  })
})

describe('closeRunning (a merge that ended without its own last event)', () => {
  it('closes whatever was running so no row keeps ticking; nothing running returns the same object', () => {
    const p = fold([ev(1, 'queued', 'running'), ev(2, 'tests', 'running')])
    const c = closeRunning(p, 'failed', 'interrupted', 99)
    expect(c.stages.tests).toMatchObject({ state: 'failed', endedAt: 99, detail: 'interrupted' })
    expect(c.outcome).toBe('failed')
    expect(closeRunning(c, 'failed', 'x', 100)).toBe(c)
    expect(closeRunning(null, 'failed')).toBe(null)
    expect(closeRunning(p, 'skipped', 'merged on GitHub', 5).outcome).toBe(null)
  })
})

describe('createMergeJoin: marvin#1223 + race condition fixes', () => {
  const URL = 'https://github.com/G-Eskayo/marvin/pull/900'

  it('join adds a reply to the set of joiners for a URL', () => {
    const join = createMergeJoin()
    const reply1 = { event: vi.fn(), result: vi.fn() }
    const reply2 = { event: vi.fn(), result: vi.fn() }
    join.join(URL, reply1)
    join.join(URL, reply2)
    join.finish(URL, 200, { merged: true })
    expect(reply1.result).toHaveBeenCalledWith(200, { merged: true })
    expect(reply2.result).toHaveBeenCalledWith(200, { merged: true })
  })

  it('event sends to all joined replies', () => {
    const join = createMergeJoin()
    const reply1 = { event: vi.fn(), result: vi.fn() }
    const reply2 = { event: vi.fn(), result: vi.fn() }
    join.join(URL, reply1)
    join.join(URL, reply2)
    const ev = { id: 'm1', seq: 1, stage: 'queued', state: 'running', at: Date.now() }
    join.event(URL, ev)
    expect(reply1.event).toHaveBeenCalledWith(ev)
    expect(reply2.event).toHaveBeenCalledWith(ev)
  })

  it('finish clears the URL so later joins for that URL start fresh', () => {
    const join = createMergeJoin()
    const reply1 = { event: vi.fn(), result: vi.fn() }
    const reply2 = { event: vi.fn(), result: vi.fn() }
    join.join(URL, reply1)
    join.finish(URL, 200, { merged: true })
    // Later join for the same URL (race condition scenario)
    join.join(URL, reply2, () => false) // isRunning says merge is done
    expect(reply1.result).toHaveBeenCalledWith(200, { merged: true })
    expect(reply2.result).toHaveBeenCalledWith(409, expect.objectContaining({ code: 'ALREADY_MERGING' }))
  })

  it('join refuses if isRunning returns false (race condition: merge already finished)', () => {
    const join = createMergeJoin()
    const reply = { event: vi.fn(), result: vi.fn() }
    const isRunning = vi.fn(() => false)
    join.join(URL, reply, isRunning)
    expect(isRunning).toHaveBeenCalledWith(URL)
    expect(reply.result).toHaveBeenCalledWith(409, expect.objectContaining({ code: 'ALREADY_MERGING' }))
    expect(reply.event).not.toHaveBeenCalled()
  })

  it('join accepts if isRunning returns true (merge still running)', () => {
    const join = createMergeJoin()
    const reply = { event: vi.fn(), result: vi.fn() }
    const isRunning = vi.fn(() => true)
    join.join(URL, reply, isRunning)
    expect(isRunning).toHaveBeenCalledWith(URL)
    // reply.result should not be called yet; this is a successful join
    expect(reply.result).not.toHaveBeenCalled()
    // Now finish the merge
    join.finish(URL, 200, { merged: true })
    expect(reply.result).toHaveBeenCalledWith(200, { merged: true })
  })

  it('join with no isRunning check works (backwards compat)', () => {
    const join = createMergeJoin()
    const reply = { event: vi.fn(), result: vi.fn() }
    join.join(URL, reply) // no isRunning, no probe
    join.finish(URL, 200, { merged: true })
    expect(reply.result).toHaveBeenCalledWith(200, { merged: true })
  })

  it('a reply that throws on event does not stop other replies from receiving events', () => {
    const join = createMergeJoin()
    const reply1 = { event: vi.fn(() => { throw new Error('reply1 error') }), result: vi.fn() }
    const reply2 = { event: vi.fn(), result: vi.fn() }
    join.join(URL, reply1)
    join.join(URL, reply2)
    const ev = { id: 'm1', seq: 1, stage: 'queued', state: 'running', at: Date.now() }
    join.event(URL, ev)
    expect(reply2.event).toHaveBeenCalledWith(ev)
  })

  it('a reply that throws on result does not stop other replies from receiving result', () => {
    const join = createMergeJoin()
    const reply1 = { event: vi.fn(), result: vi.fn(() => { throw new Error('reply1 error') }) }
    const reply2 = { event: vi.fn(), result: vi.fn() }
    join.join(URL, reply1)
    join.join(URL, reply2)
    join.finish(URL, 200, { merged: true })
    expect(reply2.result).toHaveBeenCalledWith(200, { merged: true })
  })

  it('finish for a URL with no joiners is safe (already cleared)', () => {
    const join = createMergeJoin()
    join.finish(URL, 200, { merged: true })
    // Should not throw
    join.finish(URL, 200, { merged: true })
  })

  it('event for a URL with no joiners is safe (already cleared)', () => {
    const join = createMergeJoin()
    const ev = { id: 'm1', seq: 1, stage: 'queued', state: 'running', at: Date.now() }
    join.event(URL, ev)
    // Should not throw
  })

  it('multiple URLs are independent', () => {
    const join = createMergeJoin()
    const URL2 = 'https://github.com/G-Eskayo/marvin/pull/901'
    const reply1 = { event: vi.fn(), result: vi.fn() }
    const reply2 = { event: vi.fn(), result: vi.fn() }
    join.join(URL, reply1)
    join.join(URL2, reply2)
    join.finish(URL, 200, { merged: true })
    expect(reply1.result).toHaveBeenCalledWith(200, { merged: true })
    expect(reply2.result).not.toHaveBeenCalled()
    join.finish(URL2, 200, { merged: true })
    expect(reply2.result).toHaveBeenCalledWith(200, { merged: true })
  })
})
