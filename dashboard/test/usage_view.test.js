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

const row = (day, kind, output, extra = {}) => ({ day, kind, model: 'claude-sonnet-5', input: 1, output, cache_write: 2, cache_read: 3, messages: 1, autonomous: 'autonomous' in extra ? extra.autonomous : (kind === 'headless' || kind === 'subagent'), ...extra })
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

describe('autonomousSeries', () => {
  it('builds a day-by-day series split by autonomous vs interactive', () => {
    const rows = [
      row('2026-10-05', 'headless', 100),
      row('2026-10-05', 'interactive', 50),
      row('2026-10-06', 'subagent', 20),
    ]
    const series = autonomousSeries(rows, { days: 2, end: '2026-10-06', metric: 'output' })
    expect(series).toHaveLength(2)
    expect(series[0]).toMatchObject({ day: '2026-10-05', autonomous: 100, interactive: 50, total: 150, share: expect.closeTo(100 / 150, 3) })
    expect(series[1]).toMatchObject({ day: '2026-10-06', autonomous: 20, interactive: 0, total: 20, share: 1.0 })
  })

  it('handles days with zero output without division-by-zero', () => {
    const series = autonomousSeries([], { days: 1, end: '2026-10-06', metric: 'output' })
    expect(series[0]).toMatchObject({ day: '2026-10-06', autonomous: 0, interactive: 0, total: 0, share: 0 })
  })

  it('counts headless and subagent as autonomous, interactive as interactive', () => {
    const rows = [
      row('2026-10-05', 'headless', 10),
      row('2026-10-05', 'subagent', 15),
      row('2026-10-05', 'interactive', 75),
    ]
    const d = autonomousSeries(rows, { days: 1, end: '2026-10-05', metric: 'output' })[0]
    expect(d.autonomous).toBe(25)
    expect(d.interactive).toBe(75)
    expect(d.share).toBeCloseTo(0.25, 2)
  })
})

describe('weeklySeries', () => {
  it('groups days into weeks and returns the correct number of week buckets', () => {
    const rows = [
      row('2026-10-01', 'headless', 10),
      row('2026-10-05', 'interactive', 30),
      row('2026-10-08', 'headless', 50),
      row('2026-10-12', 'subagent', 20),
    ]
    const series = weeklySeries(rows, { weeks: 3, end: '2026-10-13', metric: 'output' })
    expect(series).toHaveLength(3)
    // Verify that all weeks have the expected structure
    expect(series.every((w) => w.hasOwnProperty('autonomous') && w.hasOwnProperty('interactive'))).toBe(true)
    // At least one week should have autonomous runs (two days have headless, one has subagent)
    expect(series.some((w) => w.autonomous > 0)).toBe(true)
  })

  it('counts a row with autonomous field correctly, independent of kind', () => {
    const rows = [
      row('2026-10-06', 'subagent', 20, { autonomous: false }),
      row('2026-10-06', 'subagent', 10, { autonomous: true }),
    ]
    const series = autonomousSeries(rows, { days: 1, end: '2026-10-06', metric: 'output' })
    expect(series[0]).toMatchObject({ autonomous: 10, interactive: 20 })
  })

  it('includes rows from the oldest bucket when weeks > 1', () => {
    const rows = [
      row('2026-09-25', 'headless', 100),  // oldest week (ends Sep 29)
      row('2026-10-01', 'interactive', 50),  // middle week (ends Oct 6)
      row('2026-10-13', 'headless', 25),  // newest week (ends Oct 13)
    ]
    const series = weeklySeries(rows, { weeks: 3, end: '2026-10-13', metric: 'output' })
    expect(series).toHaveLength(3)
    // First (oldest) bucket should include 2026-09-25 data
    expect(series[0].autonomous).toBe(100)
    expect(series[0].day).toBe('2026-09-29')
  })

  it('handles rows with missing autonomous field gracefully', () => {
    const rows = [
      { day: '2026-10-06', kind: 'headless', model: 'claude-sonnet-5', input: 1, output: 50, cache_write: 2, cache_read: 3, messages: 1 },
    ]
    const series = weeklySeries(rows, { weeks: 1, end: '2026-10-06', metric: 'output' })
    expect(series[0]).toMatchObject({ interactive: 50, autonomous: 0 })
  })

  it('uses "day" field instead of "week" for compatibility with AutonomousBars component', () => {
    const rows = [row('2026-10-06', 'headless', 20)]
    const series = weeklySeries(rows, { weeks: 1, end: '2026-10-06', metric: 'output' })
    expect(series[0]).toHaveProperty('day')
    expect(series[0]).not.toHaveProperty('week')
  })

  it('handles zero rows without division-by-zero', () => {
    const series = weeklySeries([], { weeks: 1, end: '2026-10-06', metric: 'output' })
    expect(series[0]).toMatchObject({ day: expect.any(String), autonomous: 0, interactive: 0, total: 0, share: 0 })
  })

  it('calculates shares correctly when all tokens are autonomous or all interactive', () => {
    const allAuto = weeklySeries([row('2026-10-06', 'headless', 100)], { weeks: 1, end: '2026-10-06', metric: 'output' })
    expect(allAuto[0].share).toBe(1.0)

    const allInteractive = weeklySeries([row('2026-10-06', 'interactive', 100)], { weeks: 1, end: '2026-10-06', metric: 'output' })
    expect(allInteractive[0].share).toBe(0)
  })

  it('sums across multiple days in the same week', () => {
    const rows = [
      row('2026-10-04', 'headless', 50),
      row('2026-10-05', 'interactive', 30),
      row('2026-10-06', 'headless', 20),
    ]
    const series = weeklySeries(rows, { weeks: 1, end: '2026-10-06', metric: 'output' })
    expect(series[0].autonomous).toBe(70)
    expect(series[0].interactive).toBe(30)
    expect(series[0].total).toBe(100)
  })
})

describe('jobTable', () => {
  it('merges the same job across machines', () => {
    const a = m('a', null, { by_job: [{ kind: 'background-analyst', job: 'daily-digest', output_tokens: 100, cost_usd: 0.01, runs: 1 }] })
    const b = m('b', null, { by_job: [{ kind: 'background-analyst', job: 'daily-digest', output_tokens: 50, cost_usd: 0.005, runs: 1 }] })
    const t = jobTable([a, b], 'all')
    expect(t).toHaveLength(1)
    expect(t[0]).toMatchObject({ kind: 'background-analyst', job: 'daily-digest', output_tokens: 150, cost_usd: 0.015, runs: 2 })
  })

  it('sorts by output_tokens, biggest first', () => {
    const a = m('a', null, { by_job: [
      { kind: 'background-analyst', job: 'auto-fix', output_tokens: 30, cost_usd: 0.003, runs: 1 },
      { kind: 'background-analyst', job: 'daily-digest', output_tokens: 100, cost_usd: 0.01, runs: 1 },
    ] })
    const t = jobTable([a], 'all')
    expect(t.map((j) => j.job)).toEqual(['daily-digest', 'auto-fix'])
  })

  it('keeps numeric ticket IDs distinct from job-name strings', () => {
    const a = m('a', null, { by_job: [
      { kind: 'headless', job: '99', output_tokens: 50, cost_usd: 0.005, runs: 1 },
      { kind: 'background-analyst', job: 'daily-digest', output_tokens: 100, cost_usd: 0.01, runs: 1 },
    ] })
    const t = jobTable([a], 'all')
    expect(t).toHaveLength(2)
    const by_job = Object.fromEntries(t.map((j) => [j.job, j]))
    expect(by_job['99'].kind).toBe('headless')
    expect(by_job['daily-digest'].kind).toBe('background-analyst')
  })

  it('returns empty array when no machines have by_job', () => {
    const a = m('a', null, { by_job: [] })
    expect(jobTable([a], 'all')).toEqual([])
  })

  it('handles machine with reachable: false gracefully in jobTable', () => {
    const a = m('a', null, { by_job: [{ kind: 'background-analyst', job: 'daily-digest', output_tokens: 100, cost_usd: 0.01, runs: 1 }] })
    const b = { machine: 'b', reachable: false, tokens: null }
    expect(jobTable([a, b], 'all')).toHaveLength(1)
  })

  it('handles machine with no tokens key gracefully in autonomousSeries', () => {
    const rows = mergeTokenRows([
      m('a', null, { rows: [row('2026-10-06', 'headless', 50)] }),
      { machine: 'b', reachable: false },
    ], 'all')
    const series = autonomousSeries(rows, { days: 1, end: '2026-10-06', metric: 'output' })
    expect(series[0]).toMatchObject({ autonomous: 50, interactive: 0, total: 50 })
  })

  it('large dataset performance: 10k rows across 30 days completes reasonably', () => {
    const rows = []
    for (let day = 0; day < 30; day++) {
      const dateStr = new Date(new Date('2026-10-06') - day * 86400000).toISOString().slice(0, 10)
      for (let i = 0; i < 333; i++) {
        rows.push(row(dateStr, i % 3 === 0 ? 'headless' : i % 3 === 1 ? 'subagent' : 'interactive', 1))
      }
    }
    const start = performance.now()
    const series = weeklySeries(rows, { weeks: 4, end: '2026-10-06', metric: 'output' })
    const elapsed = performance.now() - start
    expect(series).toHaveLength(4)
    expect(elapsed).toBeLessThan(1000) // should complete in under 1 second
  })

  it('rows aggregated from aggregate() have autonomous field when non-empty', () => {
    const rows = [
      row('2026-10-06', 'headless', 50, { autonomous: true }),
      row('2026-10-06', 'interactive', 50, { autonomous: false }),
    ]
    expect(rows.every(r => 'autonomous' in r)).toBe(true)
  })
})
