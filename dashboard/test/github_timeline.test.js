import { describe, it, expect } from 'vitest'
import { timeline, RANGES, allowanceTone, slotDetail, readRange, writeRange } from '../src/lib/github_view.js'
import { readSaved, writeSaved, ageText } from '../src/lib/saved_state.js'

// marvin#417: hourly low-point bars linked to calls per hour, 24 h / 7 d / 30 d.
const G0 = { dashboard: 0, pipeline: 0, tests: 0, health: 0, people: 0, other: 0 }
const hr = (hour, total = 0, { groups = {}, budget_min = null, budget_readings = budget_min == null ? 0 : 1, callers = [], refused = 0, deferred = 0 } = {}) =>
  ({ hour, total, refused, deferred, groups: { ...G0, ...groups }, budget_min, budget_readings, callers })
const h = (i) => `2026-10-13T${String(i).padStart(2, '0')}:00Z`
const mac = (machine, hours) => ({ machine, github: { hours, top: [], latest_budget: null } })

describe('timeline: one slot per hour across both Macs', () => {
  const machines = [
    mac('mini', [hr(h(10), 5, { groups: { pipeline: 5 }, budget_min: 0.6, callers: [{ caller: 'ticket_pipeline.py', group: 'pipeline', calls: 5 }] }),
      hr(h(11), 2, { groups: { tests: 2 }, budget_min: 0.15 })]),
    mac('book', [hr(h(10), 1, { groups: { dashboard: 1 }, budget_min: 0.3, callers: [{ caller: 'MARVIN dashboard app', group: 'dashboard', calls: 1 }] }),
      hr(h(11), 0), hr(h(12), 3, { groups: { people: 3 } })])
  ]

  it('adds calls by hour key, not by position (clock-skewed Macs still line up)', () => {
    const t = timeline(machines, 'all', '24h')
    expect(t.slots.map((s) => s.key)).toEqual([h(10), h(11), h(12)])
    expect(t.slots.map((s) => s.total)).toEqual([6, 2, 3])
    expect(t.slots[0].groups).toMatchObject({ pipeline: 5, dashboard: 1 })
  })

  it('the allowance low point is the lower of both Macs, and an hour with no reading is a gap, never 0 or 100', () => {
    const t = timeline(machines, 'all', '24h')
    expect(t.slots.map((s) => s.budgetMin)).toEqual([0.3, 0.15, null])
  })

  it('the allowance is account-wide: picking one Mac filters calls but not the allowance', () => {
    const t = timeline(machines, 'book', '24h')
    expect(t.slots.map((s) => s.total)).toEqual([1, 0, 3])
    expect(t.slots.map((s) => s.budgetMin)).toEqual([0.3, 0.15, null])
  })

  it('callers merge across Macs into each hour\'s top list', () => {
    const t = timeline(machines, 'all', '24h')
    expect(t.slots[0].callers.map((c) => c.caller)).toEqual(['ticket_pipeline.py', 'MARVIN dashboard app'])
  })

  it('a range keeps only its last hours', () => {
    const many = [mac('mini', Array.from({ length: 300 }, (_, i) => hr(`k${String(i).padStart(4, '0')}`, 1)))]
    expect(timeline(many, 'all', '24h').slots.length).toBe(24)
    expect(timeline(many, 'all', '7d').slots.length).toBe(168)
  })

  it('30 days groups 6 hours per bar: sums calls, keeps the lowest allowance, skips gaps', () => {
    const hours = Array.from({ length: 720 }, (_, i) => hr(`k${String(i).padStart(4, '0')}`, 2, { budget_min: i === 3 ? 0.05 : i % 2 ? null : 0.8 }))
    const t = timeline([mac('mini', hours)], 'all', '30d')
    expect(t.slots.length).toBe(120)
    expect(t.slotHours).toBe(6)
    expect(t.slots[0].total).toBe(12)
    expect(t.slots[0].budgetMin).toBe(0.05)
    expect(t.slots[1].budgetMin).toBe(0.8)
  })

  it('a group with no readings at all stays a gap', () => {
    const hours = Array.from({ length: 720 }, (_, i) => hr(`k${String(i).padStart(4, '0')}`, 0))
    expect(timeline([mac('mini', hours)], 'all', '30d').slots.every((s) => s.budgetMin === null)).toBe(true)
  })

  it('nothing logged anywhere is an empty timeline, not a crash', () => {
    expect(timeline([], 'all', '24h').slots).toEqual([])
    expect(timeline([{ machine: 'x', github: null }], 'all', '7d').slots).toEqual([])
    expect(timeline([mac('x', [{ hour: h(1) }])], 'all', '24h').slots[0]).toMatchObject({ total: 0, budgetMin: null })
  })

  it('an unknown range falls back to 24 hours', () => {
    expect(timeline(machines, 'all', 'forever').range).toBe('24h')
    expect(Object.keys(RANGES)).toEqual(['24h', '7d', '30d'])
  })
})

describe('allowanceTone uses the existing thresholds', () => {
  it.each([[null, 'none'], [0, 'out'], [0.1, 'red'], [0.19, 'red'], [0.2, 'amber'], [0.49, 'amber'], [0.5, 'green'], [1, 'green']])('%s → %s', (v, tone) => {
    expect(allowanceTone(v)).toBe(tone)
  })
})

describe('slotDetail: what the clicked hour says', () => {
  it('low point, calls, split by who, top callers', () => {
    const s = { key: h(14), label: '14:00', span: '14:00', total: 1240, budgetMin: 0.18, refused: 2, deferred: 0, groups: { ...G0, pipeline: 820, dashboard: 310, tests: 110 },
      callers: [{ caller: 'ticket_pipeline.py', calls: 800 }] }
    const d = slotDetail(s)
    expect(d.headline).toBe('14:00 · low 18% · 1,240 calls')
    expect(d.split).toEqual(['Pipeline 820', 'Dashboard 310', 'Tests 110'])
    expect(d.callers).toEqual(['ticket_pipeline.py 800'])
    expect(d.refused).toBe(2)
  })
  it('no reading says so instead of a number', () => {
    expect(slotDetail({ label: '03:00', total: 0, budgetMin: null, groups: G0, callers: [] }).headline).toBe('03:00 · no allowance reading · 0 calls')
  })
  it('a 30-day bar names its whole span, and its axis label is just the date', () => {
    const hours = Array.from({ length: 720 }, (_, i) => hr(new Date(Date.UTC(2026, 8, 14, 0) + i * 3600_000).toISOString().slice(0, 13) + ':00Z', 1))
    const t = timeline([mac('mini', hours)], 'all', '30d')
    expect(t.slots[0].label).not.toMatch(/:/)
    expect(t.slots[0].span).toMatch(/–/)
    expect(slotDetail(t.slots[0]).headline).toContain(t.slots[0].span)
  })
  it('ran out says so', () => {
    expect(slotDetail({ label: '09:00', total: 9, budgetMin: 0, groups: G0, callers: [] }).headline).toBe('09:00 · ran out · 9 calls')
  })
})

describe('the chosen range is remembered, and storage failures never break the page', () => {
  const mem = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) } }
  it('round-trips', () => {
    const s = mem()
    writeRange(s, '7d')
    expect(readRange(s)).toBe('7d')
  })
  it('a junk or missing value is 24h', () => {
    const s = mem()
    expect(readRange(s)).toBe('24h')
    s.setItem('metrics.github.range', 'banana')
    expect(readRange(s)).toBe('24h')
  })
  it('throwing storage is ignored', () => {
    const bad = { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('full') } }
    expect(readRange(bad)).toBe('24h')
    expect(() => writeRange(bad, '7d')).not.toThrow()
    expect(readRange(undefined)).toBe('24h')
  })
})

describe('saved state: show the last report instantly, refresh behind it', () => {
  const mem = () => { const m = new Map(); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) } }
  it('round-trips with the time it was saved', () => {
    const s = mem()
    writeSaved(s, 'k', { machines: [1] }, 1000)
    expect(readSaved(s, 'k')).toEqual({ at: 1000, value: { machines: [1] } })
  })
  it('missing, corrupt or throwing storage gives nothing, never a crash', () => {
    const s = mem()
    expect(readSaved(s, 'k')).toBeNull()
    s.setItem('k', '{nope')
    expect(readSaved(s, 'k')).toBeNull()
    s.setItem('k', JSON.stringify({ value: 1 }))
    expect(readSaved(s, 'k')).toBeNull()
    const bad = { getItem: () => { throw new Error('x') }, setItem: () => { throw new Error('quota') } }
    expect(readSaved(bad, 'k')).toBeNull()
    expect(() => writeSaved(bad, 'k', {}, 1)).not.toThrow()
  })
  it.each([[5_000, 'updated just now'], [90_000, 'updated 1 min ago'], [2 * 3600_000, 'updated 2 h ago'], [3 * 86400_000, 'updated 3 days ago']])('%s ms → %s', (ms, text) => {
    expect(ageText(0, ms)).toBe(text)
  })
})
