import { useEffect, useState } from 'react'

// No push channel exists for "a task started/stopped" the way mr:refresh
// covers PR events -- that would mean wiring task_dispatch.py's wrapper
// script to ping refresh_server.js too. Plain poll for this first cut.
const STATUS_POLL_MS = 10000

export function formatElapsed(startedAt, now) {
  const started = new Date(startedAt).getTime()
  if (Number.isNaN(started)) return null
  const totalSeconds = Math.max(0, Math.floor((now - started) / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return minutes === 0 ? `${seconds}s` : `${minutes}m ${seconds}s`
}

export default function DispatchStatusBadge() {
  const [status, setStatus] = useState(null)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    let cancelled = false
    function refresh() {
      window.api.dispatch
        .status()
        .then((result) => {
          if (!cancelled) setStatus(result)
        })
        .catch(() => {})
    }
    refresh()
    const interval = setInterval(refresh, STATUS_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  // Ticks the elapsed-time display once a second, only while there's
  // actually something running -- no point re-rendering every second
  // while idle.
  useEffect(() => {
    if (!status?.busy) return
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [status?.busy])

  if (!status?.busy) return null

  const elapsed = formatElapsed(status.startedAt, now)

  return (
    <div className="flex items-center gap-2 text-xs text-neutral-400" title={status.task || undefined}>
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-blue-500" />
      <span className="max-w-[16rem] truncate">{status.task}</span>
      {elapsed && <span className="shrink-0 text-neutral-600">· {elapsed}</span>}
    </div>
  )
}
