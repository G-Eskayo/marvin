import { describe, it, expect } from 'vitest'
import { mergeHours, mergeBudget, mergeTop, lastHourTotals } from '../src/lib/github_view.js'

const hour = (h, total, groups = {}, extra = {}) => ({ hour: h, total, refused: 0, deferred: 0, groups: { dashboard: 0, pipeline: 0, tests: 0, health: 0, people: 0, other: 0, ...groups }, ...extra })
const machines = [
  { machine: 'mac-mini-1', github: { hours: [hour('10', 5, { tests: 5 }), hour('11', 3, { pipeline: 3 }, { refused: 1 })], top: [{ caller: 'ticket_pipeline.py', group: 'pipeline', calls: 3, refused: 1, deferred: 0, commands: [{ cmd: 'issue list', calls: 3 }] }], budget: [{ at: 100, graphql: 0.5, core: 1 }, { at: 300, graphql: 0.3, core: 1 }] } },
  { machine: 'macbook-pro-1', github: { hours: [hour('10', 1, { dashboard: 1 }), hour('11', 2, { dashboard: 2 }, { deferred: 2 })], top: [{ caller: 'MARVIN dashboard app', group: 'dashboard', calls: 2, refused: 0, deferred: 2, commands: [] }], budget: [{ at: 200, graphql: 0.4, core: 1 }] } },
  { machine: 'linux-1', github: null }
]

describe('github_view: both Macs in one picture', () => {
  it('adds the hours of both machines, group by group', () => {
    const h = mergeHours(machines, 'all')
    expect(h.map((x) => x.total)).toEqual([6, 5])
    expect(h[1].groups.pipeline).toBe(3)
    expect(h[1].groups.dashboard).toBe(2)
    expect(h[1].refused).toBe(1)
    expect(h[1].deferred).toBe(2)
  })

  it('one machine alone', () => {
    expect(mergeHours(machines, 'macbook-pro-1').map((x) => x.total)).toEqual([1, 2])
  })

  it('the allowance is account-wide: readings from both Macs form one timeline', () => {
    expect(mergeBudget(machines).map((b) => b.graphql)).toEqual([0.5, 0.4, 0.3])
  })

  it('top callers across machines, each with the machine it runs on', () => {
    const top = mergeTop(machines, 'all')
    expect(top[0]).toMatchObject({ caller: 'ticket_pipeline.py', machine: 'mac-mini-1', calls: 3 })
    expect(top.length).toBe(2)
  })

  it('last hour totals', () => {
    expect(lastHourTotals(machines, 'all')).toEqual({ total: 5, refused: 1, deferred: 2 })
  })

  it('no data anywhere is empty, not a crash', () => {
    expect(mergeHours([{ machine: 'x', github: null }], 'all')).toEqual([])
    expect(mergeBudget([])).toEqual([])
  })
})
