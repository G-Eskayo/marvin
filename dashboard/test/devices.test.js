import { describe, it, expect } from 'vitest'
import { getDeviceStatuses, clearDeviceCache } from '../electron/main/devices.js'
import { describeDevice, slotsLabel } from '../src/components/DeviceColumns.jsx'

describe('getDeviceStatuses', () => {
  it('returns the rows, caches briefly, and reports a failed check as an error (never as idle)', async () => {
    clearDeviceCache()
    let calls = 0
    const run = async () => { calls++; return '[{"id":"a","state":"idle"}]' }
    expect(await getDeviceStatuses({ run, now: 1000 })).toEqual({ devices: [{ id: 'a', state: 'idle' }], error: null })
    await getDeviceStatuses({ run, now: 3000 })
    expect(calls).toBe(1)
    clearDeviceCache()
    const bad = await getDeviceStatuses({ run: async () => { throw new Error('boom') }, now: 1000 })
    expect(bad.devices).toEqual([])
    expect(bad.error).toMatch(/boom/)
  })
})

describe('describeDevice', () => {
  const NOW = Date.parse('2026-10-05T10:05:00Z')
  it('idle', () => expect(describeDevice({ state: 'idle' }, NOW)).toMatchObject({ label: 'Idle', tone: 'idle' }))
  it('busy shows the task and elapsed time', () => {
    const d = describeDevice({ state: 'busy', task: 'ticket #5: x', startedAt: '2026-10-05T10:00:00Z' }, NOW)
    expect(d).toMatchObject({ label: 'ticket #5: x', tone: 'busy' })
    expect(d.detail).toBe('5m 0s')
  })
  it('unreachable says why', () =>
    expect(describeDevice({ state: 'unreachable', why: 'not online in Tailscale' }, NOW)).toMatchObject({ label: 'Unreachable', tone: 'down', detail: 'not online in Tailscale' }))
})

describe('slotsLabel', () => {
  it('returns null when slot data is missing', () => {
    expect(slotsLabel({ id: 'mac-mini-1' })).toBeNull()
    expect(slotsLabel({ id: 'mac-mini-1', slotsUsed: 1 })).toBeNull()
  })
  it('formats slots as "used of total"', () => {
    expect(slotsLabel({ id: 'mac-mini-1', slotsUsed: 2, slotsTotal: 4 })).toBe('2 of 4 slots')
    expect(slotsLabel({ id: 'mac-mini-1', slotsUsed: 0, slotsTotal: 2 })).toBe('0 of 2 slots')
  })
})
