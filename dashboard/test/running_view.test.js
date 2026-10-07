import { describe, it, expect } from 'vitest'
import { effectiveLimit, capacity, describeMachines } from '../src/lib/running_view.js'

const ON = { parallel: true, max_total: 4, max_per_project: 3, machine_slots: { 'mac-mini-1': 2, 'macbook-pro-1': 1 } }

describe('limits', () => {
  it('off is one per machine whatever else says', () => {
    expect(effectiveLimit({ ...ON, parallel: false }, 'mac-mini-1')).toBe(1)
    expect(capacity({ ...ON, parallel: false })).toBe(2)
  })
  it('on is the smaller of the machine slots and the total', () => {
    expect(effectiveLimit(ON, 'mac-mini-1')).toBe(2)
    expect(effectiveLimit({ ...ON, max_total: 1 }, 'mac-mini-1')).toBe(1)
  })
  it('a total above what the machines hold is capped by them (4 asked, 3 possible)', () => expect(capacity(ON)).toBe(3))
  it('a total below the machines slots caps it', () => expect(capacity({ ...ON, max_total: 2 })).toBe(2))
})

describe('describeMachines', () => {
  it('groups running tickets by machine against its limit, pairing each number with its title', () => {
    const running = [{ project: 'marvin', number: 190, title: 'Time limits', machine: 'mac-mini-1' }]
    expect(describeMachines({ running, settings: ON })).toEqual([
      { machine: 'mac-mini-1', used: 1, limit: 2, tickets: ['marvin #190 Time limits'] },
      { machine: 'macbook-pro-1', used: 0, limit: 1, tickets: [] }
    ])
  })
  it('shows a machine that is running something even if the settings do not list it', () =>
    expect(describeMachines({ running: [{ project: 'a', number: 1, title: 't', machine: 'node-3' }], settings: ON }).map((m) => m.machine)).toContain('node-3'))
})
