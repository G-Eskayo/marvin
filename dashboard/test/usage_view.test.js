import { describe, it, expect } from 'vitest'
import { mergeTools, mergeRows, mergeInventory, mergeFailures, mergeTokenRows, dailySeries, sumRows, projectTable, ticketTable, machineFreshness, autonomousSeries, weeklySeries, jobTable } from '../src/lib/usage_view.js'

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

describe('autonomous vs interactive split', () => {
  it('autonomousSeries splits one day correctly into autonomous/interactive/total/share', () => {
    const rows = [
      { day: '2026-10-06', kind: 'interactive', output: 100, input: 0, cache_write: 0, cache_read: 0, autonomous: false },
      { day: '2026-10-06', kind: 'headless', output: 200, input: 0, cache_write: 0, cache_read: 0, autonomous: true },
      { day: '2026-10-06', kind: 'subagent', output: 50, input: 0, cache_write: 0, cache_read: 0, autonomous: true }
    ]
    const series = autonomousSeries(rows, { days: 1, end: '2026-10-06' })
    expect(series).toHaveLength(1)
    expect(series[0]).toMatchObject({
      day: '2026-10-06',
      interactive: 100,
      autonomous: 250,
      total: 350,
      share: 250 / 350
    })
  })

  it('autonomousSeries with zero rows results in all zero values', () => {
    const series = autonomousSeries([], { days: 1, end: '2026-10-06' })
    expect(series).toHaveLength(1)
    expect(series[0]).toMatchObject({ day: '2026-10-06', interactive: 0, autonomous: 0, total: 0, share: 0 })
  })

  it('autonomousSeries at 100% one side returns share exactly 1 or 0', () => {
    const allInteractive = autonomousSeries([{ day: '2026-10-06', kind: 'interactive', output: 50, autonomous: false, input: 0, cache_write: 0, cache_read: 0 }], { days: 1, end: '2026-10-06' })
    expect(allInteractive[0].share).toBe(0)
    const allAutonomous = autonomousSeries([{ day: '2026-10-06', kind: 'headless', output: 50, autonomous: true, input: 0, cache_write: 0, cache_read: 0 }], { days: 1, end: '2026-10-06' })
    expect(allAutonomous[0].share).toBe(1)
  })

  it('autonomousSeries ignores rows outside the requested window', () => {
    const rows = [
      { day: '2026-10-04', kind: 'interactive', output: 100, autonomous: false, input: 0, cache_write: 0, cache_read: 0 },
      { day: '2026-10-06', kind: 'headless', output: 50, autonomous: true, input: 0, cache_write: 0, cache_read: 0 }
    ]
    const series = autonomousSeries(rows, { days: 1, end: '2026-10-06' })
    expect(series[0]).toMatchObject({ autonomous: 50, interactive: 0, total: 50 })
  })
})

describe('weekly series composition', () => {
  it('weeklySeries composes on autonomousSeries daily buckets correctly', () => {
    const rows = [
      { day: '2026-10-01', kind: 'interactive', output: 10, autonomous: false, input: 0, cache_write: 0, cache_read: 0 },
      { day: '2026-10-02', kind: 'headless', output: 20, autonomous: true, input: 0, cache_write: 0, cache_read: 0 },
      { day: '2026-10-08', kind: 'interactive', output: 100, autonomous: false, input: 0, cache_write: 0, cache_read: 0 }
    ]
    const weeks = weeklySeries(rows, { weeks: 2, end: '2026-10-08' })
    expect(weeks).toHaveLength(2)
    // Week 1: Oct 1-7 (has Oct 1 = 10 interactive, Oct 2 = 20 autonomous)
    expect(weeks[0]).toMatchObject({ interactive: 10, autonomous: 20, total: 30 })
    // Week 2: Oct 8 (has Oct 8 = 100 interactive)
    expect(weeks[1]).toMatchObject({ interactive: 100, autonomous: 0, total: 100 })
  })

  it('weeklySeries handles a window missing some days by summing what exists', () => {
    const rows = [
      { day: '2026-10-01', kind: 'interactive', output: 50, autonomous: false, input: 0, cache_write: 0, cache_read: 0 }
    ]
    const weeks = weeklySeries(rows, { weeks: 2, end: '2026-10-08' })
    expect(weeks[0]).toMatchObject({ interactive: 50, autonomous: 0, total: 50 })
    expect(weeks[1]).toMatchObject({ interactive: 0, autonomous: 0, total: 0 })
  })

  it('weeklySeries counts each day in exactly one window, not zero or two (boundary test)', () => {
    // Ensure Oct 7 (Sunday) and Oct 8 (Monday, start of new week in ISO) are in different buckets
    const rows = [
      { day: '2026-10-07', kind: 'interactive', output: 1, autonomous: false, input: 0, cache_write: 0, cache_read: 0 },
      { day: '2026-10-08', kind: 'headless', output: 2, autonomous: true, input: 0, cache_write: 0, cache_read: 0 }
    ]
    const weeks = weeklySeries(rows, { weeks: 2, end: '2026-10-08' })
    expect(weeks[0].interactive).toBe(1) // Oct 7
    expect(weeks[0].autonomous).toBe(0)
    expect(weeks[1].interactive).toBe(0)
    expect(weeks[1].autonomous).toBe(2) // Oct 8
  })
})

describe('job table (top autonomous spenders)', () => {
  it('jobTable merges same (kind, job) across machines, summing all three counters', () => {
    const a = { machine: 'mac-mini', tokens: { by_job: [{ job: 'clarity-captions', kind: 'background-analyst', output_tokens: 100, cost_usd: 0.5, runs: 2 }] } }
    const b = { machine: 'macbook', tokens: { by_job: [{ job: 'clarity-captions', kind: 'background-analyst', output_tokens: 50, cost_usd: 0.25, runs: 1 }, { job: 'marvin', kind: 'background-analyst', output_tokens: 200, cost_usd: 1.0, runs: 3 }] } }
    const table = jobTable([a, b], 'all')
    const cc = table.find(x => x.job === 'clarity-captions')
    expect(cc).toMatchObject({ job: 'clarity-captions', kind: 'background-analyst', output_tokens: 150, cost_usd: 0.75, runs: 3 })
    expect(table.map(x => x.job)).toEqual(['marvin', 'clarity-captions'])
  })

  it('jobTable tolerates a machine whose by_job is absent (older scan format)', () => {
    const a = { machine: 'mac-mini', tokens: { by_job: [{ job: 'x', kind: 'background-analyst', output_tokens: 100, cost_usd: 0.5, runs: 1 }] } }
    const b = { machine: 'macbook', tokens: {} }  // No by_job
    const table = jobTable([a, b], 'all')
    expect(table).toHaveLength(1)
    expect(table[0].job).toBe('x')
  })

  it('jobTable tolerates a machine object missing tokens entirely', () => {
    const a = { machine: 'mac-mini', tokens: { by_job: [{ job: 'x', kind: 'background-analyst', output_tokens: 100, cost_usd: 0.5, runs: 1 }] } }
    const b = { machine: 'macbook' }  // No tokens at all
    const table = jobTable([a, b], 'all')
    expect(table).toHaveLength(1)
    expect(table[0].job).toBe('x')
  })

  it('jobTable is sorted descending by output_tokens', () => {
    const a = { machine: 'mac-mini', tokens: { by_job: [
      { job: 'a', kind: 'background-analyst', output_tokens: 50, cost_usd: 0.25, runs: 1 },
      { job: 'b', kind: 'background-analyst', output_tokens: 200, cost_usd: 1.0, runs: 2 },
      { job: 'c', kind: 'background-analyst', output_tokens: 100, cost_usd: 0.5, runs: 1 }
    ] } }
    const table = jobTable([a], 'all')
    expect(table.map(x => x.job)).toEqual(['b', 'c', 'a'])
  })

  it('jobTable handles empty machines array', () => {
    const table = jobTable([], 'all')
    expect(table).toEqual([])
  })
})
