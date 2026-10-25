import { describe, it, expect } from 'vitest'
import { mergeTools, mergeRows, mergeInventory, mergeFailures, mergeTokenRows, dailySeries, sumRows, projectTable, ticketTable, machineFreshness, weeklySeries, autonomousShare, topAutonomousSpenders } from '../src/lib/usage_view.js'

const tool = (name, calls, extra = {}) => ({ name, calls, ok: calls, error: 0, rejected: 0, interrupted: 0, invalid: 0, unresolved: 0, expected: 0, last_used: null,
  by_kind: { interactive: calls, headless: 0, subagent: 0 }, by_day: {}, causes: {}, purpose: '(no description recorded)', ...extra })
const m = (machine, tools, tokens, extra = {}) => ({ machine, this: machine === 'a', reachable: true, tools: tools && { generated_at: '2026-10-06T12:00:00Z', tools, skills: [], inventory: { known: 0, used: 0, never_used: [] } }, tokens, ...extra })

describe('mergeTools', () => {
  it('adds the same tool across machines: calls, outcomes, kinds, days, and the latest use', () => {
    const a = tool('Bash', 10, { error: 2, ok: 8, last_used: '2026-10-05T10:00:00Z', by_day: { '2026-10-05': 10 } })
    const b = tool('Bash', 5, { invalid: 1, ok: 4, last_used: '2026-10-06T10:00:00Z', by_day: { '2026-10-05': 1, '2026-10-06': 4 }, by_kind: { interactive: 0, headless: 5, subagent: 0 } })
    const [row] = mergeTools([m('a', [a]), m('b', [b])], 'all')
    expect(row).toMatchObject({ name: 'Bash', calls: 15, ok: 12, error: 2, invalid: 1, last_used: '2026-10-06T10:00:00Z' })
    expect(row.by_day).toEqual({ '2026-10-05': 11, '2026-10-06': 4 })
    expect(row.by_kind).toEqual({ interactive: 10, headless: 5, subagent: 0 })
  })
  it('can look at one machine, and skips a machine with no data', () => {
    const rows = mergeTools([m('a', [tool('Read', 3)]), m('b', [tool('Read', 9)]), m('c', null)], 'b')
    expect(rows).toHaveLength(1)
    expect(rows[0].calls).toBe(9)
  })
  it('sorts by calls, most first', () => {
    expect(mergeTools([m('a', [tool('x', 1), tool('y', 5)])], 'all').map((r) => r.name)).toEqual(['y', 'x'])
  })
})

const row = (day, kind, output, extra = {}) => ({ day, kind, model: 'claude-sonnet-5', input: 1, output, cache_write: 2, cache_read: 3, messages: 1, ...extra })
const tokens = (rows, extra = {}) => ({ generated_at: '2026-10-06T12:00:00Z', rows, by_project: [], by_ticket: [], ...extra })

describe('token rows', () => {
  it('merges rows from the chosen machines', () => {
    const ms = [m('a', null, tokens([row('2026-10-05', 'headless', 100)])), m('b', null, tokens([row('2026-10-05', 'headless', 50), row('2026-10-06', 'interactive', 7)]))]
    expect(mergeTokenRows(ms, 'all')).toHaveLength(3)
    expect(mergeTokenRows(ms, 'b')).toHaveLength(2)
  })

  it('builds a day-by-day series split by kind, with empty days filled in', () => {
    const series = dailySeries([row('2026-10-04', 'headless', 100), row('2026-10-04', 'interactive', 10), row('2026-10-06', 'subagent', 5)], { days: 3, end: '2026-10-06', metric: 'output' })
    expect(series.map((d) => d.day)).toEqual(['2026-10-04', '2026-10-05', '2026-10-06'])
    expect(series[0]).toMatchObject({ headless: 100, interactive: 10, subagent: 0, total: 110 })
    expect(series[1].total).toBe(0)
    expect(series[2]).toMatchObject({ subagent: 5, total: 5 })
  })

  it("'all tokens' adds input, output and both cache counts; 'output' alone is the default", () => {
    const rows = [row('2026-10-06', 'headless', 100)]
    expect(dailySeries(rows, { days: 1, end: '2026-10-06', metric: 'output' })[0].total).toBe(100)
    expect(dailySeries(rows, { days: 1, end: '2026-10-06', metric: 'all' })[0].total).toBe(106)
  })

  it('sums a window ending at a day, and the share by kind', () => {
    const rows = [row('2026-10-01', 'headless', 10), row('2026-10-05', 'headless', 30), row('2026-10-06', 'interactive', 60)]
    const s = sumRows(rows, { days: 3, end: '2026-10-06' })
    expect(s.output).toBe(90)
    expect(s.byKind).toEqual({ interactive: 60, headless: 30, subagent: 0 })
    expect(sumRows(rows, { days: 30, end: '2026-10-06' }).output).toBe(100)
  })
})

describe('project and ticket tables', () => {
  it('merges the same project across machines, biggest first', () => {
    const a = m('a', null, tokens([], { by_project: [{ project: 'marvin', output: 10, input: 0, cache_write: 0, cache_read: 0, messages: 2, by_kind: { headless: 10 } }] }))
    const b = m('b', null, tokens([], { by_project: [{ project: 'marvin', output: 5, input: 0, cache_write: 0, cache_read: 0, messages: 1, by_kind: { interactive: 5 } }, { project: 'killer-sudoku', output: 99, input: 0, cache_write: 0, cache_read: 0, messages: 4, by_kind: {} }] }))
    const t = projectTable([a, b], 'all')
    expect(t.map((p) => p.project)).toEqual(['killer-sudoku', 'marvin'])
    expect(t[1]).toMatchObject({ output: 15, messages: 3 })
    expect(t[1].by_kind).toEqual({ headless: 10, interactive: 5 })
  })

  it('merges tickets by project and number', () => {
    const a = m('a', null, tokens([], { by_ticket: [{ project: 'marvin', ticket: 9, output: 10, messages: 1, input: 0, cache_write: 0, cache_read: 0 }] }))
    const b = m('b', null, tokens([], { by_ticket: [{ project: 'marvin', ticket: 9, output: 30, messages: 2, input: 0, cache_write: 0, cache_read: 0 }] }))
    expect(ticketTable([a, b], 'all')).toEqual([expect.objectContaining({ project: 'marvin', ticket: 9, output: 40, messages: 3 })])
  })
})

describe('machineFreshness', () => {
  it('says how old each machine\'s scan is, or that it could not be reached', () => {
    const now = Date.parse('2026-10-06T12:30:00Z')
    expect(machineFreshness(m('a', [], tokens([])), now)).toMatchObject({ state: 'ok', text: expect.stringMatching(/30 min ago/) })
    expect(machineFreshness({ machine: 'b', reachable: false, tools: null, tokens: null }, now)).toMatchObject({ state: 'unreachable' })
    expect(machineFreshness({ machine: 'b', reachable: true, tools: null, tokens: null }, now)).toMatchObject({ state: 'no-data' })
  })
})

describe('token usage autonomous metrics', () => {
  it('Test 5: weeklySeries groups daily rows into weeks', () => {
    // Create rows spanning 3 weeks, with end at the last week boundary
    const rows = [
      row('2026-10-05', 'headless', 100),
      row('2026-10-06', 'interactive', 50),
      row('2026-10-12', 'headless', 75),
      row('2026-10-19', 'subagent', 25),
      row('2026-10-20', 'interactive', 30)
    ]
    const series = weeklySeries(rows, { weeks: 4, end: '2026-10-20' })
    expect(series).toHaveLength(4)
    // Find the non-empty weeks (they won't be in series[0] due to 4-week lookback)
    const nonEmpty = series.filter(w => w.total > 0)
    expect(nonEmpty.length).toBeGreaterThanOrEqual(3)
    // Check that rows are grouped by week correctly
    const withData = series.find(w => w.headless === 100 && w.interactive === 50)
    expect(withData).toBeDefined()
    const withData2 = series.find(w => w.headless === 75)
    expect(withData2).toBeDefined()
    const withData3 = series.find(w => w.subagent === 25 && w.interactive === 30)
    expect(withData3).toBeDefined()
  })

  it('Test 6: weeklySeries respects the weeks parameter', () => {
    const rows = [
      row('2026-10-08', 'interactive', 50),
      row('2026-10-15', 'headless', 75)
    ]
    // Request only 2 weeks ending on 2026-10-15
    const series = weeklySeries(rows, { weeks: 2, end: '2026-10-15' })
    expect(series).toHaveLength(2)
    // Find weeks with data
    const week1 = series.find(w => w.interactive === 50)
    const week2 = series.find(w => w.headless === 75)
    expect(week1).toBeDefined()
    expect(week2).toBeDefined()
  })

  it('Test 7: autonomousShare calculates headless + subagent share of output tokens', () => {
    const rows = [
      row('2026-10-05', 'headless', 100),
      row('2026-10-05', 'interactive', 50),
      row('2026-10-06', 'subagent', 25)
    ]
    const s = autonomousShare(rows, { days: 2, end: '2026-10-06' })
    // total output = 100 + 50 + 25 = 175
    // autonomous = 100 + 25 = 125
    // share = 125 / 175 ≈ 0.714
    expect(s).toBeCloseTo(125 / 175, 3)
  })

  it('Test 8: autonomousShare returns 0 when there are no tokens', () => {
    const rows = []
    const s = autonomousShare(rows, { days: 7, end: '2026-10-06' })
    expect(s).toBe(0)
  })

  it('Test 9: topAutonomousSpenders returns tickets sorted by autonomous output descending', () => {
    const a = m('a', null, tokens([], {
      by_ticket: [
        { project: 'marvin', ticket: 100, output: 50, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 30, interactive: 20, subagent: 0 } },
        { project: 'marvin', ticket: 101, output: 60, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 10, interactive: 50, subagent: 0 } },
        { project: 'clarity-captions', ticket: 50, output: 100, messages: 2, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 50, interactive: 0, subagent: 50 } }
      ]
    }))
    const spenders = topAutonomousSpenders([a], 'all', 10)
    // Sorted by autonomous (headless + subagent) output descending
    expect(spenders[0]).toMatchObject({ project: 'clarity-captions', ticket: 50 })  // 50 + 50 = 100 autonomous
    expect(spenders[1]).toMatchObject({ project: 'marvin', ticket: 100 })  // 30 + 0 = 30 autonomous
    expect(spenders[2]).toMatchObject({ project: 'marvin', ticket: 101 })  // 10 + 0 = 10 autonomous
  })

  it('Test 10: topAutonomousSpenders merges same ticket across machines', () => {
    const a = m('a', null, tokens([], {
      by_ticket: [{ project: 'marvin', ticket: 9, output: 100, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 60, interactive: 40, subagent: 0 } }]
    }))
    const b = m('b', null, tokens([], {
      by_ticket: [{ project: 'marvin', ticket: 9, output: 50, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 30, interactive: 20, subagent: 0 } }]
    }))
    const spenders = topAutonomousSpenders([a, b], 'all', 10)
    expect(spenders).toHaveLength(1)
    // Autonomous = (60 + 30) = 90, interactive = (40 + 20) = 60
    expect(spenders[0]).toMatchObject({ project: 'marvin', ticket: 9, output: 150 })
    expect(spenders[0].by_kind).toEqual({ headless: 90, interactive: 60, subagent: 0 })
  })

  it('Test 11: topAutonomousSpenders respects the limit parameter', () => {
    const a = m('a', null, tokens([], {
      by_ticket: [
        { project: 'marvin', ticket: 1, output: 100, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 100, interactive: 0, subagent: 0 } },
        { project: 'marvin', ticket: 2, output: 80, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 80, interactive: 0, subagent: 0 } },
        { project: 'marvin', ticket: 3, output: 60, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 60, interactive: 0, subagent: 0 } }
      ]
    }))
    const spenders = topAutonomousSpenders([a], 'all', 2)
    expect(spenders).toHaveLength(2)
    expect(spenders[0].ticket).toBe(1)
    expect(spenders[1].ticket).toBe(2)
  })

  it('Test 12: topAutonomousSpenders filters to chosen machine', () => {
    const a = m('a', null, tokens([], {
      by_ticket: [{ project: 'marvin', ticket: 1, output: 100, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 100, interactive: 0, subagent: 0 } }]
    }))
    const b = m('b', null, tokens([], {
      by_ticket: [{ project: 'marvin', ticket: 2, output: 50, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 50, interactive: 0, subagent: 0 } }]
    }))
    const spenders = topAutonomousSpenders([a, b], 'a', 10)
    expect(spenders).toHaveLength(1)
    expect(spenders[0].ticket).toBe(1)
  })

  it('Test 16: topAutonomousSpenders filters out tickets with zero autonomous output', () => {
    const a = m('a', null, tokens([], {
      by_ticket: [
        { project: 'marvin', ticket: 1, output: 100, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 50, interactive: 50, subagent: 0 } },
        { project: 'marvin', ticket: 2, output: 100, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 0, interactive: 100, subagent: 0 } },
        { project: 'marvin', ticket: 3, output: 50, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 30, interactive: 20, subagent: 0 } }
      ]
    }))
    const spenders = topAutonomousSpenders([a], 'all', 10)
    // Should exclude ticket 2 (0 autonomous), and return tickets 1 and 3 sorted by autonomous descending
    expect(spenders).toHaveLength(2)
    expect(spenders[0].ticket).toBe(1)  // 50 autonomous
    expect(spenders[1].ticket).toBe(3)  // 30 autonomous
  })

  it('Test 17: topAutonomousSpenders includes subagent-only tickets', () => {
    const a = m('a', null, tokens([], {
      by_ticket: [
        { project: 'marvin', ticket: 1, output: 100, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 0, interactive: 100, subagent: 0 } },
        { project: 'nourished', ticket: 5, output: 80, messages: 1, input: 0, cache_write: 0, cache_read: 0, by_kind: { headless: 0, interactive: 0, subagent: 80 } }
      ]
    }))
    const spenders = topAutonomousSpenders([a], 'all', 10)
    // Should return only ticket 5 (has subagent output), exclude ticket 1 (all interactive)
    expect(spenders).toHaveLength(1)
    expect(spenders[0].ticket).toBe(5)
  })

  it('Test 18: weeklySeries includes week field and adds day field', () => {
    const rows = [
      row('2026-10-05', 'headless', 100),
      row('2026-10-06', 'interactive', 50)
    ]
    const series = weeklySeries(rows, { weeks: 1, end: '2026-10-06' })
    const weekData = series[0]
    expect(weekData).toHaveProperty('week')
    expect(weekData).toHaveProperty('day')
    expect(weekData.day).toBe(weekData.week)
  })

  it('Test 19: weeklySeries aggregates multiple days into one week bucket', () => {
    const rows = [
      row('2026-10-01', 'headless', 100),
      row('2026-10-02', 'interactive', 50),
      row('2026-10-05', 'subagent', 30),
      row('2026-10-07', 'headless', 20)  // Outside current week
    ]
    const series = weeklySeries(rows, { weeks: 2, end: '2026-10-05' })
    const currentWeek = series.find(w => w.week === '2026-10-05')
    expect(currentWeek.total).toBe(180)  // 100 + 50 + 30
    expect(currentWeek.headless).toBe(100)
    expect(currentWeek.interactive).toBe(50)
    expect(currentWeek.subagent).toBe(30)
  })

  it('Test 20: weeklySeries preserves all fields (interactive, headless, subagent, total)', () => {
    const rows = [
      row('2026-10-05', 'headless', 100),
      row('2026-10-05', 'interactive', 50),
      row('2026-10-05', 'subagent', 25)
    ]
    const series = weeklySeries(rows, { weeks: 1, end: '2026-10-05' })
    const weekData = series[0]
    expect(weekData).toMatchObject({
      headless: 100,
      interactive: 50,
      subagent: 25,
      total: 175
    })
  })
})


describe('skills, inventory and failures across machines', () => {
  const withInv = (machine, never, known = 5, failures = []) => ({ machine, reachable: true, tokens: null, tools: { generated_at: 'x', tools: [], skills: [], inventory: { known, used: known - never.length, never_used: never }, recent_failures: failures } })
  it('a skill is unused only if no chosen machine used it', () => {
    const inv = mergeInventory([withInv('a', ['x', 'y']), withInv('b', ['y', 'z'])], 'all')
    expect(inv).toEqual({ known: 5, used: 4, never_used: ['y'] })
    expect(mergeInventory([withInv('a', ['x', 'y']), withInv('b', ['y'])], 'a').never_used).toEqual(['x', 'y'])
  })
  it('merges any row list by its own name key', () => {
    const srv = (n, c) => ({ server: n, calls: c, ok: c, error: 0, rejected: 0, interrupted: 0, invalid: 0, unresolved: 0, expected: 0, last_used: null, by_kind: {}, by_day: {}, via: {}, causes: {}, purpose: '(no description recorded)' })
    const ms = [{ machine: 'a', tools: { mcp_servers: [srv('chrome', 2)] } }, { machine: 'b', tools: { mcp_servers: [srv('chrome', 3), srv('n8n', 1)] } }]
    expect(mergeRows(ms, 'all', 'mcp_servers', 'server').map((r) => [r.server, r.calls])).toEqual([['chrome', 5], ['n8n', 1]])
  })
  it('lists the newest failures first, each tagged with its machine', () => {
    const f = (at, tool) => ({ at, tool, outcome: 'error', kind: 'headless', message: 'm' })
    const out = mergeFailures([withInv('a', [], 1, [f('2026-10-05T10:00:00Z', 'Bash')]), withInv('b', [], 1, [f('2026-10-06T10:00:00Z', 'Read')])], 'all')
    expect(out.map((x) => [x.tool, x.machine])).toEqual([['Read', 'b'], ['Bash', 'a']])
  })
})
