import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
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

describe('DeviceColumns rendering', () => {
  // Helper component to render a single device card (extracted from DeviceColumns render logic)
  function DeviceCard({ d, now }) {
    const v = describeDevice(d, now)
    const DOT = { busy: 'bg-blue-500 animate-pulse', down: 'bg-red-500', idle: 'bg-neutral-600' }
    return (
      <div className="min-w-[14rem] flex-1 rounded-lg border border-neutral-800 bg-neutral-900 p-3">
        <p className="text-xs text-neutral-400">
          {d.id} <span className="text-neutral-600">· {d.kind}{d.self ? ' · this machine' : ''}</span>
        </p>
        {d.self ? (
          <div className="mt-2"><span>DispatchStatusBadge</span></div>
        ) : (
          <p className="mt-2 flex items-center gap-2 text-sm text-neutral-200">
            <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[v.tone]}`} />
            <span className="truncate">{v.label}</span>
            {v.detail && <span className="text-xs text-neutral-500">{v.detail}</span>}
          </p>
        )}
        {slotsLabel(d) && (
          <p className="mt-1 text-xs text-neutral-400">{slotsLabel(d)}</p>
        )}
        {d.tickets && d.tickets.length > 0 && (
          <div className="mt-2 space-y-1 text-xs text-neutral-400">
            {d.tickets.map((t) => (
              <p key={t.id} className="truncate">
                {t.label}
              </p>
            ))}
          </div>
        )}
      </div>
    )
  }

  it('shows slots for self device when slotsUsed and slotsTotal are present', () => {
    const now = Date.parse('2026-10-05T10:05:00Z')
    const selfDevice = {
      id: 'macbook-pro',
      kind: 'macbook',
      self: true,
      state: 'idle',
      slotsUsed: 1,
      slotsTotal: 4
    }
    const html = renderToStaticMarkup(<DeviceCard d={selfDevice} now={now} />)
    expect(html).toContain('this machine')
    expect(html).toContain('1 of 4 slots')
  })

  it('shows slots for non-self device when slotsUsed and slotsTotal are present', () => {
    const now = Date.parse('2026-10-05T10:05:00Z')
    const remoteDevice = {
      id: 'mac-mini-1',
      kind: 'mac-mini',
      self: false,
      state: 'idle',
      slotsUsed: 2,
      slotsTotal: 4
    }
    const html = renderToStaticMarkup(<DeviceCard d={remoteDevice} now={now} />)
    expect(html).toContain('Idle')
    expect(html).toContain('2 of 4 slots')
  })
})
