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

describe('autonomous share series (tests 28-37)', () => {
  const autonomousRow = (day, output) => ({ day, kind: 'headless', model: 'sonnet', input: 0, output, cache_write: 0, cache_read: 0, messages: 0 })
  const interactiveRow = (day, output) => ({ day, kind: 'interactive', model: 'sonnet', input: 0, output, cache_write: 0, cache_read: 0, messages: 0 })
  const subagentRow = (day, output) => ({ day, kind: 'subagent', model: 'sonnet', input: 0, output, cache_write: 0, cache_read: 0, messages: 0 })

  it('autonomousSeries computes share of headless+subagent output tokens per day', () => {
    const rows = [autonomousRow('2026-10-05', 100), interactiveRow('2026-10-05', 50)]
    const series = autonomousSeries(rows, { days: 1, end: '2026-10-05' })
    expect(series[0].autonomous).toBe(100)
    expect(series[0].interactive).toBe(50)
    expect(series[0].total).toBe(150)
    expect(series[0].share).toBe(67) // 100/150
  })

  it('autonomousSeries includes subagents in autonomous count', () => {
    const rows = [subagentRow('2026-10-05', 40), interactiveRow('2026-10-05', 60)]
    const series = autonomousSeries(rows, { days: 1, end: '2026-10-05' })
    expect(series[0].autonomous).toBe(40)
    expect(series[0].share).toBe(40)
  })

  it('autonomousSeries fills empty days with zero counts', () => {
    const rows = [autonomousRow('2026-10-05', 100), interactiveRow('2026-10-05', 50)]
    const series = autonomousSeries(rows, { days: 3, end: '2026-10-05' })
    expect(series.length).toBe(3)
    expect(series[1].total).toBe(0)
    expect(series[1].share).toBe(0)
  })

  it('weeklySeries buckets rows into calendar weeks and computes share', () => {
    const rows = [
      autonomousRow('2026-10-05', 100), interactiveRow('2026-10-05', 50), // Monday Oct 5 = week starting Oct 4 (Sun)
      autonomousRow('2026-10-12', 60), interactiveRow('2026-10-12', 40), // Monday Oct 12 = week starting Oct 11 (Sun)
    ]
    const series = weeklySeries(rows, { end: '2026-10-12' })
    const weeks = series.map(w => w.week)
    expect(weeks.length).toBe(12) // 12 weeks default
    const oct5week = series.find(w => w.week === '2026-10-04') // week containing Oct 5
    const oct12week = series.find(w => w.week === '2026-10-11') // week containing Oct 12
    expect(oct5week).toBeDefined()
    expect(oct5week.autonomous).toBe(100)
    expect(oct5week.share).toBe(67)
    expect(oct12week).toBeDefined()
    expect(oct12week.autonomous).toBe(60)
    expect(oct12week.share).toBe(60)
  })

  it('weeklySeries sorts by week ascending', () => {
    const rows = [autonomousRow('2026-10-05', 100)]
    const series = weeklySeries(rows, { end: '2026-10-05' })
    const weeks = series.map(w => w.week)
    for (let i = 1; i < weeks.length; i++) {
      expect(weeks[i] >= weeks[i - 1]).toBe(true)
    }
  })

  it('jobTable merges by_job across machines by ticket and returns output tokens and share', () => {
    const m1 = m('a', null, tokens([], { by_job: [{ ticket: 'job-1', output_tokens: 100, input_tokens: 10, runs: 1 }] }))
    const m2 = m('b', null, tokens([], { by_job: [{ ticket: 'job-1', output_tokens: 50, input_tokens: 5, runs: 1 }] }))
    const result = jobTable([m1, m2], 'all')
    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({ ticket: 'job-1', output_tokens: 150, share_pct: 100 })
  })

  it('jobTable sorts by output_tokens descending', () => {
    const m1 = m('a', null, tokens([], { by_job: [{ ticket: 'low', output_tokens: 10, input_tokens: 0, runs: 1 }, { ticket: 'high', output_tokens: 100, input_tokens: 0, runs: 1 }] }))
    const result = jobTable([m1], 'all')
    expect(result.map(r => r.ticket)).toEqual(['high', 'low'])
  })

  it('jobTable includes share as percentage of total output tokens', () => {
    const m1 = m('a', null, tokens([], { by_job: [{ ticket: 'a', output_tokens: 25, input_tokens: 0, runs: 1 }, { ticket: 'b', output_tokens: 75, input_tokens: 0, runs: 1 }] }))
    const result = jobTable([m1], 'all')
    expect(result[0]).toMatchObject({ ticket: 'b', share_pct: 75 })
    expect(result[1]).toMatchObject({ ticket: 'a', share_pct: 25 })
  })

  it('jobTable returns empty array when no by_job data', () => {
    const m1 = m('a', null, tokens([]))
    expect(jobTable([m1], 'all')).toEqual([])
  })

  it('autonomousSeries ignores rows with unrecognized kind and does not inflate total', () => {
    const rows = [
      autonomousRow('2026-10-05', 100),
      interactiveRow('2026-10-05', 50),
      { day: '2026-10-05', kind: 'unknown', model: 'sonnet', input: 0, output: 30, cache_write: 0, cache_read: 0, messages: 0 }
    ]
    const series = autonomousSeries(rows, { days: 1, end: '2026-10-05' })
    expect(series[0].autonomous).toBe(100)
    expect(series[0].interactive).toBe(50)
    expect(series[0].total).toBe(150) // Should NOT include the unknown kind's 30
    expect(series[0].share).toBe(67) // 100/150, not 100/180
  })

  it('weeklySeries ignores rows with unrecognized kind and does not inflate total', () => {
    const rows = [
      autonomousRow('2026-10-05', 100),
      interactiveRow('2026-10-05', 50),
      { day: '2026-10-05', kind: 'custom-agent', model: 'sonnet', input: 0, output: 25, cache_write: 0, cache_read: 0, messages: 0 }
    ]
    const series = weeklySeries(rows, { end: '2026-10-05' })
    const week = series.find(w => w.week === '2026-10-04')
    expect(week.autonomous).toBe(100)
    expect(week.interactive).toBe(50)
    expect(week.total).toBe(150) // Should NOT include the custom-agent's 25
    expect(week.share).toBe(67)
  })

  it('jobTable includes cache tokens and runs in merged result', () => {
    const m1 = m('a', null, tokens([], { by_job: [{ ticket: 'job-1', input_tokens: 50, output_tokens: 100, cache_read_tokens: 200, cache_write_tokens: 25, runs: 2 }] }))
    const m2 = m('b', null, tokens([], { by_job: [{ ticket: 'job-1', input_tokens: 30, output_tokens: 50, cache_read_tokens: 100, cache_write_tokens: 15, runs: 1 }] }))
    const result = jobTable([m1, m2], 'all')
    expect(result[0]).toMatchObject({
      ticket: 'job-1',
      output_tokens: 150,
      share_pct: 100
    })
  })

  it('pick filters machines by the which parameter and verifies jobTable uses pick', () => {
    const m1 = m('a', null, tokens([], { by_job: [{ ticket: 'job-1', output_tokens: 100, input_tokens: 10, runs: 1 }] }))
    const m2 = m('b', null, tokens([], { by_job: [{ ticket: 'job-2', output_tokens: 50, input_tokens: 5, runs: 1 }] }))
    const result = jobTable([m1, m2], 'a')
    expect(result).toHaveLength(1)
    expect(result[0].ticket).toBe('job-1')
    expect(result[0].output_tokens).toBe(100)
  })
})
