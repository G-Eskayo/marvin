import { describe, it, expect } from 'vitest'
import { MERGE_STAGES, emptyProgress, applyMergeEvent, mergeRuns, closeRunning, machineLabel, estimateLine, busyLine, opForHead } from '../src/lib/merge_progress.js'
import { createMergeJoiners } from '../webhook-server/merge_progress.js'

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

describe('createMergeJoiners: multiple approves wait for one merge result', () => {
  it('two joiners of one URL both get settled with the same result', () => {
    const joiners = createMergeJoiners()
    const replies = [
      { result: (status, body) => ({ status, body }) },
      { result: (status, body) => ({ status, body }) }
    ]
    const url = 'https://github.com/G-Eskayo/marvin/pull/1'
    joiners.join(url, replies[0])
    joiners.join(url, replies[1])
    const reply1spy = { result: (s, b) => replies[0].result = { status: s, body: b } }
    const reply2spy = { result: (s, b) => replies[1].result = { status: s, body: b } }
    // Replace with spies to track calls
    const joiners2 = createMergeJoiners()
    let call1, call2
    const r1 = { result: (s, b) => { call1 = [s, b] } }
    const r2 = { result: (s, b) => { call2 = [s, b] } }
    joiners2.join(url, r1)
    joiners2.join(url, r2)
    joiners2.settle(url, 200, { merged: true })
    expect(call1).toEqual([200, { merged: true }])
    expect(call2).toEqual([200, { merged: true }])
  })

  it('a joiner whose reply.result throws does not prevent other joiners from settling', () => {
    const joiners = createMergeJoiners()
    const url = 'https://github.com/G-Eskayo/marvin/pull/2'
    let result1Called = false
    let result2Called = false
    const r1 = { result: () => { result1Called = true; throw new Error('disconnected') } }
    const r2 = { result: () => { result2Called = true } }
    joiners.join(url, r1)
    joiners.join(url, r2)
    expect(() => joiners.settle(url, 200, {})).not.toThrow()
    expect(result1Called).toBe(true)
    expect(result2Called).toBe(true)
  })

  it('settling with no joiners registered is a no-op', () => {
    const joiners = createMergeJoiners()
    expect(() => joiners.settle('https://github.com/G-Eskayo/marvin/pull/3', 200, {})).not.toThrow()
  })

  it('joiners are keyed by URL, not global', () => {
    const joiners = createMergeJoiners()
    const url1 = 'https://github.com/G-Eskayo/marvin/pull/4'
    const url2 = 'https://github.com/G-Eskayo/marvin/pull/5'
    let call1, call2
    const r1 = { result: (s, b) => { call1 = [s, b] } }
    const r2 = { result: (s, b) => { call2 = [s, b] } }
    joiners.join(url1, r1)
    joiners.join(url2, r2)
    joiners.settle(url1, 200, { url: url1 })
    expect(call1).toEqual([200, { url: url1 }])
    expect(call2).toBeUndefined() // url2's joiner should not have been called
  })

  it('a joiner times out if settle is never called', async () => {
    const joiners = createMergeJoiners(100) // 100ms timeout
    const url = 'https://github.com/G-Eskayo/marvin/pull/6'
    let result
    const r = { result: (s, b) => { result = [s, b] } }
    joiners.join(url, r)
    // Wait for timeout to fire
    await new Promise((resolve) => setTimeout(resolve, 150))
    expect(result).toBeDefined()
    expect(result[0]).toBe(200)
    expect(result[1].code).toBe('NO_LONGER_RUNNING')
  })

  it('settling a joiner cancels its timeout', async () => {
    const joiners = createMergeJoiners(200)
    const url = 'https://github.com/G-Eskayo/marvin/pull/7'
    let result
    const r = { result: (s, b) => { result = [s, b] } }
    joiners.join(url, r)
    // Settle quickly, before timeout
    joiners.settle(url, 200, { merged: true })
    await new Promise((resolve) => setTimeout(resolve, 250))
    // The result should be from settle, not from timeout
    expect(result).toEqual([200, { merged: true }])
  })

  it('a late joiner that joins after timeout has passed also times out', async () => {
    const joiners = createMergeJoiners(100)
    const url = 'https://github.com/G-Eskayo/marvin/pull/8'
    let result1, result2
    const r1 = { result: (s, b) => { result1 = [s, b] } }
    const r2 = { result: (s, b) => { result2 = [s, b] } }
    joiners.join(url, r1)
    await new Promise((resolve) => setTimeout(resolve, 150))
    expect(result1).toBeDefined()
    expect(result1[1].code).toBe('NO_LONGER_RUNNING')
    // Late joiner has its own timeout
    joiners.join(url, r2)
    await new Promise((resolve) => setTimeout(resolve, 150))
    expect(result2).toBeDefined()
    expect(result2[1].code).toBe('NO_LONGER_RUNNING')
  })
})
