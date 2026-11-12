import { useEffect, useState } from 'react'
import DispatchStatusBadge, { formatElapsed, agoShort } from './DispatchStatusBadge.jsx'
import { MoonIcon } from './HealthDashboard.jsx'

const POLL_MS = 15000 // backstop only: a remote machine has no push channel

export function describeDevice(d, now) {
  if (d.state === 'busy') return { label: d.task || 'Busy', tone: 'busy', detail: d.startedAt ? formatElapsed(d.startedAt, now) : null, icon: null }
  if (d.state === 'unreachable') {
    const tone = d.severity === 'asleep' ? 'asleep' : d.severity === 'yellow' ? 'yellow' : 'down'
    const icon = d.severity === 'asleep' ? 'moon' : null
    const detail = d.lastSeen ? `last seen ${agoShort(d.lastSeen, now)}` : (d.why || null)
    return { label: d.severity === 'asleep' ? 'Asleep' : 'Unreachable', tone, detail, icon }
  }
  return { label: 'Idle', tone: 'idle', detail: null, icon: null }
}

export function slotsLabel(d) {
  if (d.slotsUsed === undefined || d.slotsTotal === undefined) return null
  return `${d.slotsUsed} of ${d.slotsTotal} slots`
}

const DOT = { busy: 'bg-blue-500 animate-pulse', down: 'bg-red-500', idle: 'bg-neutral-600', asleep: 'bg-sky-400', yellow: 'bg-amber-500' }

// One column per device in marvin-network.json. This machine's column is the same DispatchStatusBadge
// that sits in the header (its richer view: every running agent, last finished); the others come from
// the cross-machine reader.
export default function DeviceColumns() {
  const [state, setState] = useState({ devices: [], error: null })
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    let cancelled = false
    const refresh = () => window.api.devices.status().then((r) => !cancelled && setState(r)).catch(() => {})
    refresh()
    const i = setInterval(refresh, POLL_MS)
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => { cancelled = true; clearInterval(i); clearInterval(t) }
  }, [])

  if (state.error) return <p className="mb-4 text-xs text-red-400">{state.error}</p>
  if (!state.devices.length) return null
  return (
    <div className="mb-4 flex flex-wrap gap-3" data-testid="device-columns">
      {state.devices.map((d) => {
        const v = describeDevice(d, now)
        return (
          <div key={d.id} className="min-w-[14rem] flex-1 rounded-lg border border-neutral-800 bg-neutral-900 p-3">
            <p className="text-xs text-neutral-400">
              {d.id} <span className="text-neutral-600">· {d.kind}{d.self ? ' · this machine' : ''}</span>
            </p>
            {d.self ? (
              <div className="mt-2"><DispatchStatusBadge /></div>
            ) : (
              <p className="mt-2 flex items-center gap-2 text-sm text-neutral-200">
                {v.icon === 'moon' ? (
                  <MoonIcon className="h-2.5 w-2.5" />
                ) : (
                  <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[v.tone]}`} />
                )}
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
                    {t.label} {t.started_at && <span className="text-neutral-600">({formatElapsed(t.started_at, now)})</span>}
                  </p>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
