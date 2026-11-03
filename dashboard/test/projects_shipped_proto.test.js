import { describe, it, expect } from 'vitest'
// Workshop ▸ Projects and Shipped (marvin#864), the mock-up's logic. These try to break the rules behind every count,
// order and line the mock-up shows. It is a classic script (the page opens without a build), so it sets
// globalThis.ProjectsShipped.
import '../../docs/design/864-projects-shipped/projects_shipped.js'

const P = globalThis.ProjectsShipped
const NOW = new Date(2026, 10, 3, 15, 0).getTime()
const H = 3600_000

const item = (section, extra = {}) => ({ type: 'pr', number: 1, title: 't', section, stage: 4, ...extra })
const project = (id, items = [], extra = {}) => ({ id, name: id, items, ...extra })

describe('orderProjects: #935’s order, Activity’s fold', () => {
  it('puts the most "your move" first, then size, then name, and Other last', () => {
    const got = P.orderProjects([
      project('other', [item('yours'), item('yours'), item('yours')]),
      project('b', [item('marvin'), item('marvin')], { name: 'Beta' }),
      project('a', [item('marvin'), item('marvin')], { name: 'alpha' }),
      project('c', [item('yours')]),
      project('d', [item('marvin'), item('marvin'), item('marvin')])
    ])
    expect(got.active.map((p) => p.id)).toEqual(['c', 'd', 'a', 'b', 'other'])
  })
  it('folds parked, done and archived away, by name, even when they have open items', () => {
    const got = P.orderProjects([project('z', [], { status: 'parked' }), project('y', [item('yours')], { status: 'done' }), project('x', [], { status: 'archived' }), project('w')])
    expect(got.active.map((p) => p.id)).toEqual(['w'])
    expect(got.rest.map((p) => p.id)).toEqual(['x', 'y', 'z'])
  })
  it('leaves out an empty Other and anything without an id, and survives garbage', () => {
    expect(P.orderProjects([project('other'), null, { name: 'no id' }, project('a')]).active.map((p) => p.id)).toEqual(['a'])
    expect(P.orderProjects(undefined)).toEqual({ active: [], rest: [] })
    expect(P.orderProjects('nope')).toEqual({ active: [], rest: [] })
  })
})

describe('isCollapsed: #935’s quiet rule', () => {
  it('opens a project with something for you or something stuck, closes the rest', () => {
    expect(P.isCollapsed(project('a', [item('yours')]))).toBe(false)
    expect(P.isCollapsed(project('a', [item('stuck')]))).toBe(false)
    expect(P.isCollapsed(project('a', [item('marvin'), item('next')]))).toBe(true)
  })
  it('lets your saved choice win both ways, except an empty project stays closed', () => {
    expect(P.isCollapsed(project('a', [item('yours')]), { a: true })).toBe(true)
    expect(P.isCollapsed(project('a', [item('marvin')]), { a: false })).toBe(false)
    expect(P.isCollapsed(project('a', []), { a: false })).toBe(true)
  })
})

describe('the header lines', () => {
  it('says the ticket’s words, stuck first, up next only when there is some', () => {
    expect(P.moveLine(project('a', [item('yours'), item('marvin'), item('marvin')]))).toBe('1 your move · 2 in motion')
    expect(P.moveLine(project('a', [item('stuck'), item('next')]))).toBe('1 stuck · 0 your move · 0 in motion · 1 up next')
  })
  it('names what your moves are, like #935’s summary, for tickets and PRs', () => {
    const p = project('a', [
      item('yours', { verb: 'Answer 3 decisions' }), item('yours', { verb: 'Approve' }), item('yours', { verb: 'Approve' }),
      item('yours', { verb: 'Approve the look' }), item('yours', { verb: 'Give info', type: 'ticket' }), item('yours', { verb: 'Weigh a proposal' }),
      item('marvin', { verb: 'Approve' })
    ])
    expect(P.yoursLine(p)).toBe('1 decision · 2 to approve · 1 look · 1 to answer · 1 other')
    expect(P.yoursLine(project('a', [item('marvin')]))).toBe('nothing for you')
  })
  it('reads moving, stuck and held truthfully', () => {
    expect(P.stateOf(project('a', [item('stuck'), item('stuck')]))).toEqual({ text: 'stuck 2', tone: 'red' })
    expect(P.stateOf(project('a', [], { held: 2 }))).toEqual({ text: 'held', tone: 'amber' })
    expect(P.stateOf(project('a', [item('yours')], { held: 2, mergedWeek: 0 })).text).not.toBe('held')
    expect(P.stateOf(project('a', [], { mergedWeek: 4 })).text).toBe('moving')
    expect(P.stateOf(project('a', [item('marvin')])).text).toBe('moving')
    expect(P.stateOf(project('a', [], { mergedWeek: 'lots' })).text).toBe('—')
  })
  it('counts the whole page for the lede, Other not counted as a project', () => {
    const groups = [project('a', [item('yours'), item('stuck')]), project('b', [item('marvin')]), project('other', [item('yours')])]
    expect(P.lede(groups)).toBe('2 active projects · 2 your move · 1 in motion · 1 stuck')
    expect(P.lede([])).toBe('0 active projects · 0 your move · 0 in motion')
  })
  it('cuts the goal to its first clause, never empty-handed', () => {
    expect(P.shortGoal('Any hard-of-hearing person can rely on Seal Speak: iPhone first, then Android.')).toBe('Any hard-of-hearing person can rely on Seal Speak')
    expect(P.shortGoal('Ship it.')).toBe('Ship it')
    expect(P.shortGoal(null)).toBe('')
    expect(P.shortGoal('x'.repeat(200)).length).toBeLessThanOrEqual(110)
  })
})

describe('sectionsOf: the headings inside an open project', () => {
  const p = project('a', [
    item('yours', { number: 5, priority: 'p2', waitingMin: 10 }),
    item('yours', { number: 6, priority: 'p1', waitingMin: 5 }),
    item('yours', { number: 7, priority: 'p2', waitingMin: 300 }),
    item('marvin', { number: 8, tier: 'running' }),
    item('stuck', { number: 9, tier: 'stuck' }),
    item('next', { type: 'ticket', number: 10 }),
    item('weird', { number: 11 }),
    item('waiting', { number: 12, isDraft: true })
  ])
  it('in Now’s words: priority first, then the oldest wait; an unknown section is shown, never dropped', () => {
    const s = P.sectionsOf(p, 'now')
    expect(s.map((x) => x.id)).toEqual(['stuck', 'yours', 'marvin', 'next', 'waiting'])
    expect(s[1].items.map((x) => x.number)).toEqual([6, 7, 5])
    expect(s[4].items.map((x) => x.number)).toEqual([11, 12])
  })
  it('in #935’s words: PRs by their tier, tickets placed by their section, drafts in Draft', () => {
    const s = P.sectionsOf(p, '935')
    expect(s.map((x) => x.id)).toEqual(['needs-you', 'running', 'waiting', 'stuck', 'draft'])
    expect(s.find((x) => x.id === 'waiting').items.map((x) => x.number)).toEqual([10])
    expect(s.find((x) => x.id === 'draft').items.map((x) => x.number)).toEqual([12])
    // A PR with no tier and an unknown section lands in Being fixed, where someone will see it.
    expect(s.find((x) => x.id === 'stuck').items.map((x) => x.number)).toEqual([9, 11])
  })
  it('keeps every item exactly once, in either words', () => {
    for (const w of ['now', '935']) expect(P.sectionsOf(p, w).flatMap((x) => x.items).length).toBe(8)
  })
})

describe('lanesOf (#1028): one lane per feature, Unsorted last', () => {
  it('counts each lane and never drops an item without one', () => {
    const lanes = P.lanesOf(project('a', [item('yours', { lane: 'Vitals' }), item('marvin', { lane: 'Dashboard' }), item('marvin', { lane: 'Dashboard' }), item('next'), null]))
    expect(lanes.map((l) => [l.name, l.total, l.yours, l.marvin])).toEqual([['Vitals', 1, 1, 0], ['Dashboard', 2, 0, 2], ['Unsorted', 1, 0, 0]])
  })
})

describe('the life track and strip', () => {
  it('counts items per stage, shows the most urgent tone, ignores stages that don’t exist', () => {
    const t = P.trackOf(project('a', [item('marvin', { stage: 3 }), item('stuck', { stage: 3 }), item('yours', { stage: 2 }), item('yours', { stage: 99 }), item('yours', { stage: 'x' })]))
    expect(t.map((s) => s.count)).toEqual([0, 0, 1, 2, 0, 0, 0])
    expect(t[3].tone).toBe('stuck')
  })
  it('pulses a stop only when something real happened there (truthful motion)', () => {
    expect(P.trackOf(project('a', [item('marvin', { stage: 3 })]))[3].live).toBe(false)
    expect(P.trackOf(project('a', [item('marvin', { stage: 3, liveEvent: true })]))[3].live).toBe(true)
    expect(P.trackOf(project('a', [item('yours', { stage: 3, liveEvent: true })]))[3].live).toBe(false)
  })
  it('lights the item’s own stage in its tone and clamps a stage out of range', () => {
    expect(P.stripOf(item('yours', { stage: 2 }))).toEqual(['done', 'done', 'yours', 'todo', 'todo', 'todo', 'todo'])
    expect(P.stripOf(item('marvin', { stage: 40 }))[6]).toBe('marvin')
    expect(P.stripOf(item('marvin', { stage: -3 }))[0]).toBe('marvin')
  })
})

describe('liveLine: where the work is live (ADR 0080 I4)', () => {
  const merged = (live) => ({ kind: 'merged', live })
  const macs = { kind: 'macs', targets: ['MacBook', 'Mini'] }
  it('says plainly when the project has no ship step yet', () => {
    expect(P.liveLine(merged({ state: 'live' }), null)).toEqual({ text: 'no ship step yet', tone: 'dim', marks: [] })
    expect(P.liveLine(merged(), { kind: 'teleport' }).text).toBe('no ship step yet')
  })
  it('counts the Macs that pulled, and names the ones still pulling', () => {
    expect(P.liveLine(merged({ pulled: ['MacBook', 'Mini'] }), macs).text).toBe('live on both Macs')
    const half = P.liveLine(merged({ pulled: ['Mini'] }), macs)
    expect(half.text).toBe('live on 1 of 2 · MacBook pulling')
    expect(half.marks).toEqual([{ name: 'MacBook', on: false }, { name: 'Mini', on: true }])
    expect(P.liveLine(merged({ pulled: ['Elsewhere'] }), macs).text).toBe('live on 0 of 2 · MacBook, Mini pulling')
    expect(P.liveLine(merged({}), { kind: 'macs', targets: [] }).tone).toBe('red')
  })
  it('handles TestFlight and a site, each state', () => {
    expect(P.liveLine(merged({ state: 'live', build: '1.1.0 (10)' }), { kind: 'testflight' }).text).toBe('TestFlight 1.1.0 (10)')
    expect(P.liveLine(merged({ state: 'shipping' }), { kind: 'testflight' }).tone).toBe('amber')
    expect(P.liveLine(merged(), { kind: 'testflight' }).text).toBe('waits for the next TestFlight build')
    expect(P.liveLine(merged({ state: 'live' }), { kind: 'pages', where: 'gh-pages' }).text).toBe('live on gh-pages')
    expect(P.liveLine(merged({ state: 'shipping' }), { kind: 'pages' }).text).toBe('publishing to the site')
  })
  it('shows a failed ship in red with its reason, and nothing for a refused approve', () => {
    expect(P.liveLine(merged({ state: 'failed', reason: 'upload rejected' }), { kind: 'testflight' })).toEqual({ text: 'ship failed: upload rejected', tone: 'red', marks: [] })
    expect(P.liveLine({ kind: 'refused' }, macs)).toBeNull()
    expect(P.liveLine(null, macs)).toBeNull()
  })
})

describe('Shipped: days, pages, the lede', () => {
  const rows = [
    { kind: 'merged', at: new Date(NOW - 1 * H).toISOString(), project: 'marvin', live: { pulled: ['MacBook', 'Mini'] } },
    { kind: 'refused', at: new Date(NOW - 2 * H).toISOString(), project: 'marvin' },
    { kind: 'merged', at: new Date(NOW - 24 * H).toISOString(), project: 'seal' },
    { kind: 'merged', at: new Date(NOW - 9 * 24 * H).toISOString(), project: 'marvin', live: {} },
    { kind: 'merged', at: 'whenever', project: 'marvin' }
  ]
  it('groups newest first under Today and Yesterday, and keeps a row with no time under its own heading', () => {
    const d = P.shippedDays(rows, NOW)
    expect(d.map((x) => x.label).slice(0, 2)).toEqual(['Today', 'Yesterday'])
    expect(d[0].rows.map((r) => r.kind)).toEqual(['merged', 'refused'])
    expect(d[d.length - 1]).toMatchObject({ key: 'unknown', label: 'Time not recorded' })
    expect(d.flatMap((x) => x.rows).length).toBe(5)
  })
  it('pages 5 days at a time and clamps a page out of range', () => {
    const days = Array.from({ length: 12 }, (_, i) => ({ key: String(i), rows: [] }))
    expect(P.pageOf(days, 0)).toMatchObject({ page: 0, pages: 3 })
    expect(P.pageOf(days, 9).page).toBe(2)
    expect(P.pageOf(days, -1).days.length).toBe(5)
    expect(P.pageOf([], 0)).toMatchObject({ page: 0, pages: 1, days: [] })
  })
  it('counts this week only, and says "live" only once some project has a ship step', () => {
    expect(P.shippedLede(rows, {}, NOW)).toBe('this week: 2 merged · 1 refused')
    expect(P.shippedLede(rows, { marvin: { kind: 'macs', targets: ['MacBook', 'Mini'] } }, NOW)).toBe('this week: 2 merged · 1 live · 1 refused')
  })
  it('bins ships per day, oldest first, refused and unreadable rows left out', () => {
    const bars = P.perDay(rows, NOW, 14)
    expect(bars.length).toBe(14)
    expect(bars[13].n).toBe(1)
    expect(bars[12].n).toBe(1)
    expect(bars.reduce((s, b) => s + b.n, 0)).toBe(3)
  })
})
