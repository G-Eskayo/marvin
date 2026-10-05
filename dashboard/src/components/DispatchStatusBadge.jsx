import { useEffect, useState } from 'react'

// A backstop only: runs and steps are pushed (the run-log folder is watched and fires an 'agents'
// trigger), so this poll just covers a task launched by the dispatch system, which has no push channel.
const STATUS_POLL_MS = 10000

export function formatElapsed(startedAt, now) {
  const started = new Date(startedAt).getTime()
  if (Number.isNaN(started)) return null
  const totalSeconds = Math.max(0, Math.floor((now - started) / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return minutes === 0 ? `${seconds}s` : `${minutes}m ${seconds}s`
}

function agoShort(iso, now) {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

// Always visible, so "idle" can never be mistaken for "gone": it says what is running right now (the
// dispatched task and every background agent mid-run, with the step it is on), or Idle with what
// finished last. `working` is null only until the first reading arrives.
export function WorkingView({ working, now, onClick }) {
  if (!working) return null
  const [first, ...rest] = working.items
  const body = first ? (
    <>
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-blue-500" />
      <span className="max-w-[18rem] truncate text-neutral-200">{first.label}</span>
      {first.detail && <span className="max-w-[16rem] truncate text-neutral-500">{first.detail}</span>}
      {first.startedAt && <span className="shrink-0 text-neutral-600">· {formatElapsed(first.startedAt, now)}</span>}
      {rest.length > 0 && <span className="shrink-0 text-neutral-500">+{rest.length} more</span>}
    </>
  ) : (
    <>
      <span className="h-2 w-2 shrink-0 rounded-full bg-neutral-600" />
      <span className="text-neutral-500">Idle</span>
      {working.last && (
        <span className="max-w-[20rem] truncate text-neutral-600">
          · last: {working.last.label}
          {working.last.summary ? ` (${working.last.summary})` : ''} {agoShort(working.last.finishedAt, now)}
        </span>
      )}
    </>
  )
  const title = first ? [first.label, first.detail].filter(Boolean).join(' — ') : 'Nothing is running on this machine right now'
  return (
    <button onClick={onClick} title={`${title}. Click for all agents.`} className="flex items-center gap-2 text-xs text-neutral-400 hover:text-neutral-200">
      {body}
    </button>
  )
}

export default function DispatchStatusBadge({ onClick }) {
  const [working, setWorking] = useState(null)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    let cancelled = false
    const refresh = () =>
      window.api.working
        .now()
        .then((r) => !cancelled && setWorking(r))
        .catch(() => {})
    refresh()
    const interval = setInterval(refresh, STATUS_POLL_MS)
    const off = window.api.triggers.on((t) => t.topic === 'agents' && refresh())
    return () => {
      cancelled = true
      clearInterval(interval)
      off()
    }
  }, [])

  // Tick the elapsed time once a second only while something is running.
  const busy = !!working?.items.length
  useEffect(() => {
    if (!busy) return
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [busy])

  return <WorkingView working={working} now={now} onClick={onClick} />
}
