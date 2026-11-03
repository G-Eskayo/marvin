import { describe, it, expect } from 'vitest'
// Plan usage + the one throttle switch (marvin#872), the mock-up's logic. These try to break describeThrottle(), the one
// rule behind every word the mock-up's card shows. It is a classic script (the page opens without a build), so it sets
// globalThis.UsageToggle.
import '../../docs/design/872-usage-toggle/usage_toggle.js'

const { describeThrottle, stepOf, paceOf, windowsSummary, LINES } = globalThis.UsageToggle

const NOW = Date.parse('2026-11-03T14:00:00Z')
const H = 3600_000
const reading = (fivePct, weekPct, extra = {}) => ({
  recorded_at: new Date(NOW - 60_000).toISOString(),
  five_hour: { used_pct: fivePct, resets_at: new Date(NOW + 2 * H).toISOString() },
  seven_day: { used_pct: weekPct, resets_at: new Date(NOW + 3 * 24 * H).toISOString() },
  windows: [],
  weekly_pace: null,
  ...extra
})
const slots = { max: 4 }
const running = [{ title: 'Vitals foundation', kind: 'build' }, { title: 'Disk first aid', kind: 'fix' }]
const view = (usage, on = true, more = {}) => describeThrottle({ usage, on, running, queued: 5, slots, now: NOW, ...more })

describe('the lines, in order', () => {
  it('uses the CONTEXT.md lines: soft about 90, warn near 95, hard about 99', () => {
    expect(LINES).toEqual({ soft: 90, warn: 95, hard: 99 })
  })
  it.each([[0, 'clear'], [89, 'clear'], [89.9, 'clear'], [90, 'soft'], [94.9, 'soft'], [95, 'warn'], [98.9, 'warn'], [99, 'hard'], [100, 'hard'], [130, 'hard']])(
    '%s%% is %s', (pct, step) => expect(stepOf(pct)).toBe(step))
  it('the tighter of the 5-hour window and the week decides', () => {
    expect(view(reading(40, 96)).step).toBe('warn')
    expect(view(reading(99, 10)).step).toBe('hard')
    expect(view(reading(91, 50)).heldBy).toMatch(/5-hour window 91%/)
    expect(view(reading(20, 96)).heldBy).toMatch(/week 96%/)
  })
})

describe('on: full power, held to the tightest limit', () => {
  it('clear: every slot is open and nothing holds it', () => {
    const v = view(reading(42, 58))
    expect(v.step).toBe('clear')
    expect(v.newWork).toBe(4)
    expect(v.heldBy).toBeNull()
    expect(v.headline).toMatch(/Full power/)
  })
  it('soft line: background pauses first, builds move cheaper, and new builds still start', () => {
    const v = view(reading(91, 60))
    expect(v.newWork).toBe(4)
    expect(v.doing.join(' ')).toMatch(/background/i)
    expect(v.doing.join(' ')).toMatch(/cheaper model|API credit/)
  })
  it('hard line: nothing new starts, the running build finishes, fix work still passes', () => {
    const v = view(reading(99, 60))
    expect(v.newWork).toBe(0)
    expect(v.doing.join(' ')).toMatch(/The running build finishes/)
    expect(view(reading(99, 60), true, { running: [...running, running[0]] }).doing.join(' ')).toMatch(/The 2 running builds finish/)
    expect(v.doing.join(' ')).toMatch(/[Ff]ix work still runs/)
    expect(v.headline).toMatch(/resets/)
  })
})

describe('off: one at a time per Mac, and the guardrails never switch off', () => {
  it('clear: one per Mac, said in words', () => {
    const v = view(reading(42, 58), false)
    expect(v.newWork).toBe(1)
    expect(v.headline).toMatch(/one at a time/i)
  })
  it('the hard line still holds new work when off', () => {
    expect(view(reading(99.5, 60), false).newWork).toBe(0)
  })
  it('the guardrails are the same list either way', () => {
    expect(view(reading(42, 58), false).guardrails).toEqual(view(reading(42, 58), true).guardrails)
    expect(view(reading(42, 58)).guardrails.length).toBeGreaterThanOrEqual(4)
  })
})

describe('it says what flipping it will do, before you flip it', () => {
  it('on to off names the running work that finishes', () => {
    expect(view(reading(42, 58)).flip).toMatch(/Turn off: new tickets go one at a time per Mac\. The 2 running now finish\./)
  })
  it('off to on names the current tightest limit', () => {
    expect(view(reading(42, 58), false).flip).toMatch(/Turn on: up to 4 at once/)
  })
  it('at the hard line flipping changes nothing now, and it says so', () => {
    expect(view(reading(99, 60)).flip).toMatch(/changes nothing until/)
    expect(view(reading(99, 60), false).flip).toMatch(/changes nothing until/)
  })
  it('one running: said in the singular', () => {
    expect(describeThrottle({ usage: reading(42, 58), on: true, running: [running[0]], queued: 0, slots, now: NOW }).flip).toMatch(/The one running now finishes\./)
  })
  it('nothing running: no "0 running" sentence', () => {
    expect(describeThrottle({ usage: reading(42, 58), on: true, running: [], queued: 0, slots, now: NOW }).flip).not.toMatch(/0 running/)
  })
})

describe('unknown and not enough data are never 0% or healthy', () => {
  it('no reading at all: not enough data yet, and the fixed guards run it', () => {
    const v = view(null)
    expect(v.reading).toBe('none')
    expect(v.five.text).toBe('not enough data yet')
    expect(v.five.pct).toBeNull()
    expect(v.step).toBe('unknown')
    expect(v.headline).not.toMatch(/0%/)
  })
  it('a stale reading keeps the last known step, never "clear"', () => {
    const old = { ...reading(92, 60), recorded_at: new Date(NOW - 3 * H).toISOString() }
    const v = view(old, true, { lastStep: 'soft' })
    expect(v.reading).toBe('stale')
    expect(v.step).toBe('soft')
    expect(v.headline).toMatch(/last known/i)
  })
  it('a stale reading with no last step is unknown, and holds to one per Mac', () => {
    const old = { ...reading(10, 10), recorded_at: new Date(NOW - 3 * H).toISOString() }
    const v = view(old)
    expect(v.step).toBe('unknown')
    expect(v.newWork).toBe(1)
  })
  it('a reset time that has passed while shed: everything resumes (the old reading no longer counts)', () => {
    const passed = reading(99, 40, { five_hour: { used_pct: 99, resets_at: new Date(NOW - 60_000).toISOString() } })
    const v = view(passed)
    expect(v.five.text).toMatch(/reset/i)
    expect(v.step).not.toBe('hard')
  })
  it('garbage numbers do not crash and do not read as 0%', () => {
    const v = view({ ...reading(42, 58), five_hour: { used_pct: 'lots', resets_at: 'soon' } })
    expect(v.five.pct).toBeNull()
    expect(v.five.text).toBe('not enough data yet')
  })
})

describe('pace and the windows behind it', () => {
  it('pace: under, on and over the week, and unknown without one', () => {
    expect(paceOf(70)).toBe('under')
    expect(paceOf(95)).toBe('on')
    expect(paceOf(104)).toBe('over')
    expect(paceOf(null)).toBe('unknown')
    expect(paceOf('x')).toBe('unknown')
  })
  it('counts windows that hit the limit and windows left unused', () => {
    const w = (peak, hit = false) => ({ start: '2026-11-01T00:00:00Z', end: '2026-11-01T05:00:00Z', peak_pct: peak, hit_limit: hit })
    const s = windowsSummary([w(100, true), w(4), w(0), w(60), w(97)])
    expect(s).toMatchObject({ total: 5, hitLimit: 1, unused: 2 })
    expect(s.leftPct).toBe(Math.round(((99 - 4) + (99 - 0) + (99 - 60) + (99 - 97)) / 5))
  })
  it('no windows yet: not enough data, not "0 hit the limit"', () => {
    expect(windowsSummary([])).toMatchObject({ total: 0, text: 'not enough data yet' })
    expect(windowsSummary(undefined)).toMatchObject({ total: 0 })
  })
})
