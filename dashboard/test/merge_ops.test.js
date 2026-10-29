import { describe, it, expect, vi } from 'vitest'
import { createMergeOps } from '../electron/main/merge_ops.js'

const URL = 'https://github.com/o/r/pull/5'

describe('merge ops (survives the renderer navigating away)', () => {
  it('is idle until a merge starts, merging while it runs', () => {
    const ops = createMergeOps()
    expect(ops.get(URL)).toEqual({ state: 'idle' })
    ops.start(URL)
    expect(ops.get(URL).state).toBe('merging')
  })

  it('remembers a re-engagement or failure so the message is still there on return', () => {
    const ops = createMergeOps()
    ops.start(URL)
    ops.finish(URL, { reengaged: true, reason: 'rebase conflict' })
    expect(ops.get(URL)).toMatchObject({ state: 'reengaged', reason: 'rebase conflict' })
    ops.start(URL)
    ops.fail(URL, 'webhook down')
    expect(ops.get(URL)).toMatchObject({ state: 'error', reason: 'webhook down' })
  })

  it('a merged attempt reads "merged" (#568: the card shows Done until the list drops the PR); a cancelled one leaves nothing', () => {
    const ops = createMergeOps()
    ops.start(URL); ops.finish(URL, { merged: true })
    expect(ops.get(URL).state).toBe('merged')
    ops.start(URL); ops.cancel(URL)
    expect(ops.get(URL)).toEqual({ state: 'idle' })
  })

  it('refuses a second concurrent start for the same PR (double click, or a second window)', () => {
    const ops = createMergeOps()
    expect(ops.start(URL)).toBe(true)
    expect(ops.start(URL)).toBe(false)
  })

  it('tracks PRs independently', () => {
    const ops = createMergeOps()
    ops.start(URL)
    expect(ops.get('https://github.com/o/r/pull/6').state).toBe('idle')
  })
})

describe('a merge that never reports back does not stay "merging" forever', () => {
  it('expires into an error after the limit, so the card stops saying Merging', () => {
    const ops = createMergeOps({ maxMergingMs: 1000 })
    ops.start(URL)
    const t0 = Date.now()
    expect(ops.get(URL, t0 + 500).state).toBe('merging')
    const late = ops.get(URL, t0 + 5000)
    expect(late.state).toBe('error')
    expect(late.reason).toMatch(/did not finish|timed out/i)
  })
  it('after it expires a new attempt may start', () => {
    const ops = createMergeOps({ maxMergingMs: 1000 })
    ops.start(URL)
    expect(ops.start(URL, Date.now() + 5000)).toBe(true)
  })
})

// Gil, 2026-10-21: "the last merge attempt failed" stayed on #559 after a fix was pushed, so the card looked stale.
// A failure belongs to the commit it happened on; a new head means a new PR state.
describe('a failure clears once a new commit is pushed', () => {
  it('reports the failure while the head is unchanged', () => {
    const ops = createMergeOps()
    ops.start(URL, Date.now(), 'aaa111')
    ops.fail(URL, 'Tests fail on the latest main')
    expect(ops.get(URL, Date.now(), 'aaa111')).toMatchObject({ state: 'error', reason: 'Tests fail on the latest main' })
  })
  it('is idle again when the PR has a newer head', () => {
    const ops = createMergeOps()
    ops.start(URL, Date.now(), 'aaa111')
    ops.fail(URL, 'Tests fail on the latest main')
    expect(ops.get(URL, Date.now(), 'bbb222').state).toBe('idle')
  })
  it('a re-engagement also clears on a new head', () => {
    const ops = createMergeOps()
    ops.start(URL, Date.now(), 'aaa111')
    ops.finish(URL, { reengaged: true, reason: 'sent back' })
    expect(ops.get(URL, Date.now(), 'bbb222').state).toBe('idle')
  })
  it('keeps the failure when the head is unknown on either side (older callers), so nothing is hidden', () => {
    const ops = createMergeOps()
    ops.start(URL)
    ops.fail(URL, 'boom')
    expect(ops.get(URL, Date.now(), 'bbb222').state).toBe('error')
    const ops2 = createMergeOps()
    ops2.start(URL, Date.now(), 'aaa111')
    ops2.fail(URL, 'boom')
    expect(ops2.get(URL).state).toBe('error')
  })
  it('never hides a merge that is still running, whatever head is asked about', () => {
    const ops = createMergeOps()
    ops.start(URL, Date.now(), 'aaa111')
    expect(ops.get(URL, Date.now(), 'bbb222').state).toBe('merging')
  })
})

// marvin#568: the merge's stage events, pushed from the webhook, are folded into the op the card reads.
describe('merge progress events (push, not polling)', () => {
  const ev = (seq, stage, state, extra = {}) => ({ id: 'm1', seq, stage, state, at: 1000 + seq, ...extra })

  it('events update the running op; the mount-time read returns the progress so far', () => {
    const ops = createMergeOps()
    ops.start(URL, 0, 'aaa')
    ops.event(URL, ev(1, 'queued', 'running'))
    ops.event(URL, ev(2, 'tests', 'running', { count: { done: 3, total: 10, unit: 'files' } }))
    const op = ops.get(URL, 10, 'aaa')
    expect(op.state).toBe('merging')
    expect(op.progress.stages.tests).toMatchObject({ state: 'running', count: { done: 3, total: 10 } })
  })

  it('a duplicate or late event returns null (nothing to push), and changes nothing', () => {
    const ops = createMergeOps()
    ops.start(URL)
    expect(ops.event(URL, ev(2, 'fetching', 'running'))).not.toBe(null)
    expect(ops.event(URL, ev(2, 'fetching', 'running'))).toBe(null)
    expect(ops.event(URL, ev(1, 'queued', 'running'))).toBe(null)
  })

  it('an event for a PR with no merge here adopts it (a merge started from the phone, seen through the local ping)', () => {
    const ops = createMergeOps()
    const op = ops.event(URL, ev(1, 'queued', 'running'), 50)
    expect(op.state).toBe('merging')
    expect(ops.start(URL, 60)).toBe(false) // and this window cannot start a second one on top of it
  })

  it('an adopted merge ends on its own events: done -> merged, a failed stage -> error with the detail', () => {
    const ops = createMergeOps()
    ops.event(URL, ev(1, 'merging', 'running'))
    expect(ops.event(URL, ev(2, 'done', 'done')).state).toBe('merged')
    const other = 'https://github.com/o/r/pull/7'
    ops.event(other, ev(1, 'tests', 'running'))
    expect(ops.event(other, ev(2, 'tests', 'failed', { detail: 'GATE_TESTS_FAILED: 2 failing test(s)' }))).toMatchObject({ state: 'error', reason: 'GATE_TESTS_FAILED: 2 failing test(s)' })
  })

  it('a stray event for a finished attempt does not resurrect it', () => {
    const ops = createMergeOps()
    ops.start(URL); ops.fail(URL, 'boom')
    expect(ops.event(URL, { ...ev(9, 'tests', 'running'), id: 'old' })).toBe(null)
    expect(ops.get(URL).state).toBe('error')
  })

  it('the time limit counts from the last event, so a long merge that keeps reporting is not given up on', () => {
    const ops = createMergeOps({ maxMergingMs: 1000 })
    ops.start(URL, 0)
    ops.event(URL, ev(1, 'tests', 'running'), 900)
    ops.event(URL, ev(2, 'tests', 'running', { count: { done: 1, total: 2 } }), 1800)
    expect(ops.get(URL, 2500).state).toBe('merging')
    expect(ops.get(URL, 2900).state).toBe('error')
  })
})

describe('a merge lost to a webhook restart reads "interrupted" at once, not "Merging…" for 45 minutes', () => {
  it('interrupt() ends the op with the plain message, keeping the progress so far', () => {
    const ops = createMergeOps()
    ops.start(URL, 0, 'aaa')
    ops.event(URL, { id: 'm1', seq: 1, stage: 'tests', state: 'running', at: 1 })
    const op = ops.interrupt(URL)
    expect(op.state).toBe('interrupted')
    expect(op.reason).toBe('The merge was interrupted when the webhook restarted. Approve again.')
    expect(op.progress.stages.tests).toMatchObject({ state: 'failed', detail: 'interrupted: the webhook restarted' }) // no row keeps ticking
    expect(ops.start(URL)).toBe(true) // Approve again works straight away
  })

  it('an interrupted event (sent by the webhook as it starts again) does the same for an adopted merge', () => {
    const ops = createMergeOps()
    ops.event(URL, { id: 'm1', seq: 1, stage: 'tests', state: 'running', at: 1 })
    expect(ops.event(URL, { id: 'm1', seq: 2, stage: 'tests', state: 'failed', interrupted: true, at: 2 }).state).toBe('interrupted')
  })

  it('interrupting a PR that is not merging does nothing', () => {
    const ops = createMergeOps()
    expect(ops.interrupt(URL)).toBe(null)
    ops.start(URL); ops.finish(URL, { merged: true })
    expect(ops.interrupt(URL)).toBe(null)
    expect(ops.get(URL).state).toBe('merged')
  })
})

describe('a PR merged on GitHub while the dashboard shows "Merging…"', () => {
  const view = (state) => vi.fn(async () => ({ state }))

  it('the change-detector\'s next event ends the op as "Merged on GitHub"', async () => {
    const ops = createMergeOps()
    ops.start(URL)
    ops.event(URL, { id: 'm1', seq: 1, stage: 'tests', state: 'running', at: 1 })
    const changed = await ops.githubChanged('o/r', view('MERGED'))
    expect(changed).toEqual([URL])
    expect(ops.get(URL)).toMatchObject({ state: 'merged', elsewhere: true, reason: 'Merged on GitHub' })
  })

  it('the gate\'s own merge (Merging on GitHub already done) is not "elsewhere"', async () => {
    const ops = createMergeOps()
    ops.start(URL)
    ops.event(URL, { id: 'm1', seq: 1, stage: 'merging', state: 'done', at: 1 })
    expect(await ops.githubChanged('o/r', view('MERGED'))).toEqual([])
    expect(ops.get(URL).state).toBe('merging')
  })

  it('still open: nothing changes; another repo\'s change asks GitHub nothing', async () => {
    const ops = createMergeOps()
    ops.start(URL)
    const v = view('OPEN')
    expect(await ops.githubChanged('o/r', v)).toEqual([])
    expect(await ops.githubChanged('x/y', v)).toEqual([])
    expect(v).toHaveBeenCalledTimes(1)
    expect(ops.get(URL).state).toBe('merging')
  })

  it('a change for any repo (unknown source) checks every merging op; a GitHub error is not a merge', async () => {
    const ops = createMergeOps()
    ops.start(URL)
    expect(await ops.githubChanged(null, vi.fn(async () => { throw new Error('rate limited') }))).toEqual([])
    expect(ops.get(URL).state).toBe('merging')
  })

  it('the webhook answering later (an "already merged" error) does not overwrite "Merged on GitHub"', async () => {
    const ops = createMergeOps()
    ops.start(URL)
    await ops.githubChanged('o/r', view('MERGED'))
    ops.fail(URL, 'MERGE_REFUSED: Pull request is already merged')
    expect(ops.get(URL)).toMatchObject({ state: 'merged', elsewhere: true })
    ops.finish(URL, { reengaged: true, reason: 'x' })
    expect(ops.get(URL).state).toBe('merged')
  })

  it('asks GitHub at most once per merging op per change, and never for finished ones', async () => {
    const ops = createMergeOps()
    for (let i = 0; i < 5; i++) { ops.start(`https://github.com/o/r/pull/${i}`); if (i > 1) ops.fail(`https://github.com/o/r/pull/${i}`, 'x') }
    const v = view('OPEN')
    await ops.githubChanged('o/r', v)
    expect(v).toHaveBeenCalledTimes(2)
  })

  it('closed on GitHub (not merged) ends it too, so it is not asked about again and again', async () => {
    const ops = createMergeOps()
    ops.start(URL)
    expect(await ops.githubChanged(null, view('CLOSED'), Date.now(), new Set([URL]))).toEqual([URL])
    expect(ops.get(URL)).toMatchObject({ state: 'error', reason: 'The PR was closed on GitHub while it was merging.' })
    expect(ops.mergingUrls()).toEqual([])
  })

  it('`only` limits the check to the PRs missing from a fresh open list', async () => {
    const ops = createMergeOps()
    ops.start(URL); ops.start('https://github.com/o/r/pull/9')
    const v = view('OPEN')
    await ops.githubChanged(null, v, Date.now(), new Set([URL]))
    expect(v).toHaveBeenCalledTimes(1)
    expect(v).toHaveBeenCalledWith(URL)
  })
})

describe('a new merge started elsewhere after one finished here', () => {
  it('its first event (seq 1, a new id) is adopted; a straggler from the finished one is not', () => {
    const ops = createMergeOps()
    ops.start(URL)
    ops.event(URL, { id: 'old', seq: 1, stage: 'queued', state: 'running', at: 1 })
    ops.fail(URL, 'boom')
    expect(ops.event(URL, { id: 'old', seq: 2, stage: 'fetching', state: 'running', at: 2 })).toBe(null)
    expect(ops.event(URL, { id: 'new', seq: 1, stage: 'queued', state: 'running', at: 3 }).state).toBe('merging')
  })
})

// marvin#762: the Mini down. The op carries the plain-words notice while the MacBook merges, and a queued state
// (no machine could take it) that the card shows and a later retry can start from.
describe('failover notice and queued approvals', () => {
  it('notice() puts the plain words on a running merge, and pushing an event keeps them', () => {
    const ops = createMergeOps()
    ops.start(URL)
    expect(ops.notice(URL, 'The Mac mini is offline, merging on this MacBook Pro instead.')).toMatchObject({ state: 'merging', notice: 'The Mac mini is offline, merging on this MacBook Pro instead.' })
    ops.event(URL, { id: 'b', seq: 1, stage: 'queued', state: 'running', at: 1 })
    expect(ops.get(URL).notice).toBe('The Mac mini is offline, merging on this MacBook Pro instead.')
  })

  it('notice() on a PR that is not merging changes nothing', () => {
    const ops = createMergeOps()
    expect(ops.notice(URL, 'x')).toBe(null)
    expect(ops.get(URL)).toEqual({ state: 'idle' })
  })

  it('queue() ends the running op as queued with its reason; a retry may start it again', () => {
    const ops = createMergeOps()
    ops.start(URL, 1, 'abc')
    expect(ops.queue(URL, 'Neither Mac can merge right now', 2)).toMatchObject({ state: 'queued', reason: 'Neither Mac can merge right now', head: 'abc' })
    expect(ops.mergingUrls()).toEqual([])
    expect(ops.start(URL, 3)).toBe(true)
  })

  it('a queued op is shown for any head: the approval is still waiting even if the PR moved on', () => {
    const ops = createMergeOps()
    ops.start(URL, 1, 'abc')
    ops.queue(URL, 'why', 2)
    expect(ops.get(URL, 3, 'def').state).toBe('queued')
  })

  it('cancelQueued() clears a queued op (Deny), and leaves a running merge alone', () => {
    const ops = createMergeOps()
    ops.start(URL); ops.queue(URL, 'why')
    expect(ops.cancelQueued(URL)).toBe(true)
    expect(ops.get(URL)).toEqual({ state: 'idle' })
    ops.start(URL)
    expect(ops.cancelQueued(URL)).toBe(false)
    expect(ops.get(URL).state).toBe('merging')
  })
})
