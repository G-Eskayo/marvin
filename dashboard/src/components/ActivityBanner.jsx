import { useEffect, useState } from 'react'

const RED_CHECK_IDS = new Set([
  'pipeline:breaker',
  'deploy:missing:',
  'sync:stuck:',
])

function isRedCheck(checkId) {
  if (!checkId) return false
  for (const prefix of RED_CHECK_IDS) {
    if (checkId.startsWith(prefix)) return true
  }
  return false
}

function formatTime(isoString) {
  if (!isoString) return 'unknown time'
  try {
    const date = new Date(isoString)
    return date.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
  } catch {
    return 'unknown time'
  }
}

export default function ActivityBanner() {
  const [redChecks, setRedChecks] = useState([])

  useEffect(() => {
    const loadStatus = () => {
      window.api.health
        .status()
        .then((result) => {
          const red = (result.checks || []).filter(
            (check) => check.severity === 'red' && isRedCheck(check.id)
          )
          setRedChecks(red)
        })
        .catch(() => setRedChecks([]))
    }

    loadStatus()
    const interval = setInterval(loadStatus, 60_000)
    return () => clearInterval(interval)
  }, [])

  if (!redChecks.length) return null

  return (
    <div className="mb-4 space-y-2 rounded-lg border border-red-900 bg-red-950 p-3">
      {redChecks.map((check) => (
        <div key={check.id} className="flex items-start gap-2 text-sm">
          <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-red-500" />
          <div className="flex-1 min-w-0">
            <p className="font-medium text-red-300 truncate">{check.label}</p>
            <p className="text-xs text-red-400 line-clamp-2">{check.detail}</p>
          </div>
        </div>
      ))}
    </div>
  )
}
