import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import path from 'path'
import { renderToStaticMarkup } from 'react-dom/server'
import MergeProgress from '../src/components/MergeProgress.jsx'
import { statusFromOp } from '../src/components/MrReview.jsx'
import { describePrState } from '../src/lib/prState.js'
import { emptyProgress, applyMergeEvent } from '../src/lib/merge_progress.js'

// marvin#568: the merge's stages drawn with #557's CheckProgress, unchanged.
const T0 = Date.parse('2026-10-21T19:00:00Z')
const ev = (seq, stage, state, at, extra = {}) => ({ id: 'm1', seq, stage, state, at: T0 + at * 1000, ...extra })
const fold = (events) => events.reduce(applyMergeEvent, emptyProgress())
const text = (h) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
const midTests = fold([
  ev(1, 'queued', 'running', 0),
  ev(2, 'fetching', 'running', 2, { machine: { id: 'mac-mini-1', busy: false, load: 2.1, cores: 10 } }),
  ev(3, 'fetching', 'done', 6, { estimateMs: 185_000 }),
  ev(4, 'rebasing', 'running', 6), ev(5, 'rebasing', 'done', 14),
  ev(6, 'installing', 'running', 14), ev(7, 'installing', 'done', 44),
  ev(8, 'tests', 'running', 44, { detail: 'Dashboard', count: { done: 120, total: 183, unit: 'files' } })
])

describe('MergeProgress', () => {
  it('collapsed: the bar, "N of 8 done", the running stage with its live count and time, the estimate and machine', () => {
    const h = renderToStaticMarkup(<MergeProgress progress={midTests} now={T0 + 116_000} />)
    expect(h).toContain('data-check-progress') // #557's component, not a copy
    expect(text(h)).toContain('4 of 8 done') // queued, fetching, rebasing, installing
    expect(text(h)).toContain('Still running: Tests · Dashboard 120/183 · 1:12 ') // stages not reached are not "running"
    expect(text(h)).not.toContain('Merging on GitHub')
    expect(text(h)).toContain('Usually about 3 min · on Mac mini')
    expect(h).not.toContain('data-merge-busy')
  })

  it('expanded: one row per stage with waiting / running / done words and each stage\'s time', () => {
    const h = renderToStaticMarkup(<MergeProgress progress={midTests} now={T0 + 116_000} defaultOpen />)
    const rows = h.match(/data-check-row="[^"]*"/g)
    expect(rows).toHaveLength(8)
    expect(text(h)).toMatch(/✓ Queued done 0:02/)
    expect(text(h)).toMatch(/✓ Installing done 0:30/)
    expect(text(h)).toMatch(/◌ Tests · Dashboard 120\/183 running 1:12/)
    expect(text(h)).toMatch(/◌ Merging on GitHub waiting/)
  })

  it('busy machine: a plain warning under the bar', () => {
    const busy = applyMergeEvent(midTests, ev(9, 'tests', 'running', 50, { machine: { id: 'mac-mini-1', busy: true, load: 9.4, cores: 10, top: 'engine test' } }))
    const h = renderToStaticMarkup(<MergeProgress progress={busy} now={T0 + 60_000} />)
    expect(text(h)).toContain('Mac mini is busy (engine test running); this may be slow')
  })

  it('a failed stage: red bar, the row marked ✗ with why', () => {
    const failed = applyMergeEvent(midTests, ev(9, 'tests', 'failed', 90, { detail: 'GATE_TESTS_FAILED: 2 failing test(s)' }))
    const h = renderToStaticMarkup(<MergeProgress progress={failed} now={T0 + 100_000} defaultOpen />)
    expect(h).toContain('bg-red-400')
    expect(h).toContain('data-merge-progress="failed"')
    expect(text(h)).toMatch(/✗ Tests failed 0:46/)
  })

  it('done: green and full', () => {
    const done = fold([ev(1, 'queued', 'running', 0), ev(2, 'fetching', 'running', 1), ev(3, 'rebasing', 'skipped', 2), ev(4, 'installing', 'skipped', 2), ev(5, 'tests', 'skipped', 2), ev(6, 'merging', 'running', 2), ev(7, 'after', 'running', 9), ev(8, 'done', 'done', 10)])
    const h = renderToStaticMarkup(<MergeProgress progress={done} now={T0 + 11_000} />)
    expect(h).toContain('bg-emerald-400')
    expect(h).toMatch(/style="width:100%"/)
    expect(text(h)).toContain('8 of 8 done')
  })

  it('a machine name from outside is text, never markup', () => {
    const p = applyMergeEvent(emptyProgress(), ev(1, 'fetching', 'running', 0, { machine: { id: '<img src=x onerror=alert(1)>', busy: true } }))
    const h = renderToStaticMarkup(<MergeProgress progress={p} now={T0} />)
    expect(h).not.toContain('<img')
  })

  it('nothing to show without progress', () => {
    expect(renderToStaticMarkup(<MergeProgress progress={null} />)).toBe('')
  })
})

describe('the card\'s status from the main process\'s op', () => {
  it('maps each op state', () => {
    expect(statusFromOp({ state: 'merging', progress: midTests })).toEqual({ status: 'approving', errorMessage: null, progress: midTests })
    expect(statusFromOp({ state: 'interrupted', reason: 'The merge was interrupted when the webhook restarted. Approve again.' }).status).toBe('interrupted')
    expect(statusFromOp({ state: 'merged', elsewhere: true, reason: 'Merged on GitHub' })).toMatchObject({ status: 'merged', errorMessage: 'Merged on GitHub' })
    expect(statusFromOp({ state: 'merged' })).toMatchObject({ status: 'merged', errorMessage: null })
    expect(statusFromOp({ state: 'idle' }).status).toBe('idle')
    expect(statusFromOp(undefined).status).toBe('idle')
  })

  it('headlines: interrupted says so and offers Approve again; merged on GitHub says what happened', () => {
    const pr = { number: 559, checks: { state: 'passing', failing: [], pending: [] } }
    const i = describePrState(pr, { status: 'interrupted', errorMessage: 'The merge was interrupted when the webhook restarted. Approve again.' })
    expect(i).toMatchObject({ kind: 'interrupted', headline: 'The merge was interrupted', approve: 'enabled' })
    expect(i.detail).toBe('The merge was interrupted when the webhook restarted. Approve again.')
    expect(describePrState(pr, { status: 'merged', errorMessage: 'Merged on GitHub' })).toMatchObject({ headline: 'Merged on GitHub', approve: 'hidden' })
    expect(describePrState(pr, { status: 'merged' })).toMatchObject({ headline: 'Merged', tone: 'ready' })
    expect(describePrState(pr, { status: 'approving', progress: true }).detail).toBe('You can leave this screen; it carries on.')
  })
})

describe('the card subscribes; it does not poll (guard #556 checks the timers, this checks the wiring)', () => {
  const src = readFileSync(path.join(__dirname, '..', 'src', 'components', 'MrReview.jsx'), 'utf8')
  const actions = src.slice(src.indexOf('export function ApproveDenyActions'), src.indexOf('async function handleApprove'))
  it('one mergeState read and one onMergeEvent subscription, cleaned up, no timer', () => {
    expect(actions.match(/mergeState\(/g)).toHaveLength(1)
    expect(actions).toContain('onMergeEvent')
    expect(actions).toMatch(/return \(\) => \{ cancelled = true; off\?\.\(\) \}/)
    expect(actions).not.toMatch(/setTimeout|setInterval/)
  })
})

// marvin#762: the Mac mini down, in plain words on the card.
describe('failover and queued approvals on the card', () => {
  const pr = { number: 900, checks: { state: 'passing', failing: [], pending: [] } }
  const NOTICE = 'The Mac mini is offline, merging on this MacBook Pro instead.'
  const WHY = "Neither Mac can merge right now: the Mac mini is offline, and this MacBook Pro's merge service isn't running. Your approval is saved and will merge by itself when one comes back."

  it('a merge failed over carries its notice; one without a notice reads as before', () => {
    expect(statusFromOp({ state: 'merging', notice: NOTICE, progress: null })).toEqual({ status: 'approving', errorMessage: NOTICE, progress: null })
    const v = describePrState(pr, { status: 'approving', errorMessage: NOTICE, progress: true })
    expect(v).toMatchObject({ kind: 'merging', headline: 'Merging…', approve: 'hidden' })
    expect(v.detail).toBe(`${NOTICE} You can leave this screen; it carries on.`)
  })

  it('queued: says why and that it will merge by itself; Approve hidden (it is already saved), Deny still there to cancel it', () => {
    expect(statusFromOp({ state: 'queued', reason: WHY })).toMatchObject({ status: 'queued', errorMessage: WHY })
    const v = describePrState(pr, { status: 'queued', errorMessage: WHY })
    expect(v).toMatchObject({ kind: 'queued', headline: 'Approved: waiting for a Mac to merge it', approve: 'hidden', deny: 'enabled' })
    expect(v.detail).toBe(WHY)
  })
})
