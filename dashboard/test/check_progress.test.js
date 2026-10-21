import { describe, it, expect } from 'vitest'
import { summarizeChecks, formatClock, formatAgo, runningLine, toMs } from '../src/lib/check_progress.js'

// marvin#555: the numbers behind "2 of 3 done · Still running: App builds (iOS) · 4:05 · Last checked 20 s ago".
const NOW = Date.parse('2026-10-21T06:02:07Z')
const passed = (name, s, c) => ({ name, status: 'passed', done: true, startedAt: s, completedAt: c })
const running = (name, s) => ({ name, status: 'running', done: false, startedAt: s, completedAt: null })
const queued = (name) => ({ name, status: 'queued', done: false, startedAt: null, completedAt: null })

const gilsExample = [
  passed('Website checks', '2026-10-21T05:58:02Z', '2026-10-21T05:58:50Z'),
  passed('CaptionCore unit tests', '2026-10-21T05:58:03Z', '2026-10-21T06:01:15Z'),
  running('App builds (iOS)', '2026-10-21T05:58:02Z')
]

describe('formatClock', () => {
  it('m:ss under an hour, h:mm:ss above', () => {
    expect(formatClock(48_000)).toBe('0:48')
    expect(formatClock(245_000)).toBe('4:05')
    expect(formatClock(59 * 60_000 + 59_999)).toBe('59:59')
    expect(formatClock(3_723_000)).toBe('1:02:03')
    expect(formatClock(0)).toBe('0:00')
  })
  it('clock skew (a negative time) shows 0:00, never "-1:-5"; unknown shows nothing', () => {
    expect(formatClock(-5000)).toBe('0:00')
    expect(formatClock(null)).toBe('')
    expect(formatClock(undefined)).toBe('')
    expect(formatClock(NaN)).toBe('')
    expect(formatClock(Infinity)).toBe('')
  })
})

describe('formatAgo', () => {
  it('seconds, then minutes, then hours', () => {
    expect(formatAgo(20_400)).toBe('20 s ago')
    expect(formatAgo(59_999)).toBe('59 s ago')
    expect(formatAgo(60_000)).toBe('1 min ago')
    expect(formatAgo(42 * 60_000)).toBe('42 min ago')
    expect(formatAgo(3 * 3_600_000 + 5)).toBe('3 h ago')
  })
  it('a timestamp from the future (skew) is "0 s ago"; unknown is null', () => {
    expect(formatAgo(-9000)).toBe('0 s ago')
    expect(formatAgo(null)).toBe(null)
    expect(formatAgo(NaN)).toBe(null)
  })
})

describe('toMs', () => {
  it('accepts epoch ms and ISO strings; anything else is null', () => {
    expect(toMs(1234)).toBe(1234)
    expect(toMs('2026-10-21T06:02:07Z')).toBe(NOW)
    expect(toMs('not a date')).toBe(null)
    expect(toMs('')).toBe(null)
    expect(toMs(null)).toBe(null)
    expect(toMs({})).toBe(null)
    expect(toMs(0)).toBe(null) // epoch zero is never a real GitHub time
  })
})

describe('summarizeChecks', () => {
  it("Gil's example: 2 of 3 done, the running one named with time since it started", () => {
    const s = summarizeChecks(gilsExample, NOW)
    expect(s).toMatchObject({ total: 3, done: 2, percent: 67 })
    expect(s.running).toEqual([{ name: 'App builds (iOS)', status: 'running', time: 245_000 }])
    expect(s.rows.map((r) => [r.name, r.label, formatClock(r.time)])).toEqual([
      ['Website checks', 'passed', '0:48'],
      ['CaptionCore unit tests', 'passed', '3:12'],
      ['App builds (iOS)', 'running', '4:05']
    ])
  })

  it('no checks at all: nothing to show, and no division by zero', () => {
    expect(summarizeChecks([], NOW)).toEqual({ total: 0, done: 0, percent: 0, running: [], rows: [] })
    expect(summarizeChecks(null, NOW)).toEqual({ total: 0, done: 0, percent: 0, running: [], rows: [] })
    expect(summarizeChecks([null, 'x'], NOW).total).toBe(0)
  })

  it('all pending: 0 of N, an empty bar', () => {
    const s = summarizeChecks([queued('a'), running('b', '2026-10-21T06:00:00Z')], NOW)
    expect(s).toMatchObject({ total: 2, done: 0, percent: 0 })
    expect(s.running.map((r) => r.name)).toEqual(['a', 'b'])
  })

  it('every finished check counts as done, whatever its conclusion; the bar can be full', () => {
    const s = summarizeChecks([passed('a'), { name: 'b', status: 'failed', done: true }, { name: 'c', status: 'skipped', done: true }], NOW)
    expect(s).toMatchObject({ done: 3, total: 3, percent: 100, running: [] })
  })

  it('missing startedAt: no time shown (not "since 1970"), still counted', () => {
    const s = summarizeChecks([queued('Lint'), { name: 'x', status: 'passed', done: true, startedAt: null, completedAt: '2026-10-21T06:00:00Z' }], NOW)
    expect(s.rows.map((r) => r.time)).toEqual([null, null])
    expect(s.running[0].time).toBe(null)
  })

  it('clock skew: a start in the future, or a finish before the start, is 0 not negative', () => {
    const s = summarizeChecks([running('a', '2026-10-21T06:05:00Z'), passed('b', '2026-10-21T06:00:10Z', '2026-10-21T06:00:00Z')], NOW)
    expect(s.rows.map((r) => r.time)).toEqual([0, 0])
  })

  it('garbage timestamps are treated as missing', () => {
    expect(summarizeChecks([running('a', 'yesterday')], NOW).rows[0].time).toBe(null)
  })

  it('one check, and twelve checks', () => {
    expect(summarizeChecks([running('only', '2026-10-21T06:02:00Z')], NOW)).toMatchObject({ total: 1, done: 0, percent: 0 })
    const twelve = Array.from({ length: 12 }, (_, i) => (i < 7 ? passed(`p${i}`, '2026-10-21T06:00:00Z', '2026-10-21T06:01:00Z') : running(`r${i}`, '2026-10-21T06:00:00Z')))
    const s = summarizeChecks(twelve, NOW)
    expect(s).toMatchObject({ total: 12, done: 7, percent: 58 })
    expect(s.rows).toHaveLength(12)
    expect(s.running).toHaveLength(5)
  })

  it('an unknown status is shown as it is named, and not counted as done unless GitHub said so', () => {
    const s = summarizeChecks([{ name: 'x', status: 'weird', done: false }], NOW)
    expect(s.rows[0].label).toBe('weird')
    expect(s.done).toBe(0)
  })
})

describe('runningLine', () => {
  it('names the running check with its time', () => {
    expect(runningLine(summarizeChecks(gilsExample, NOW))).toBe('App builds (iOS) · 4:05')
  })
  it('a queued check has no time yet, so just its name', () => {
    expect(runningLine(summarizeChecks([queued('Lint')], NOW))).toBe('Lint')
  })
  it('several are listed, and many are cut to two plus a count', () => {
    const two = summarizeChecks([running('a', '2026-10-21T06:02:00Z'), running('b', '2026-10-21T06:01:07Z')], NOW)
    expect(runningLine(two)).toBe('a · 0:07, b · 1:00')
    const five = summarizeChecks(['a', 'b', 'c', 'd', 'e'].map((n) => running(n, '2026-10-21T06:02:00Z')), NOW)
    expect(runningLine(five)).toBe('a · 0:07, b · 0:07 and 3 more')
  })
  it('nothing running: empty', () => {
    expect(runningLine(summarizeChecks([passed('a')], NOW))).toBe('')
  })
})
