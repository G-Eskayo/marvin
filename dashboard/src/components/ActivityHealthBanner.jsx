import { useEffect, useState } from 'react'

const BANNER_CHECK_IDS = ['pipeline:stopped', 'sync:stuck', 'deploy:missing']

export default function ActivityHealthBanner() {
  const [checks, setChecks] = useState([])

  useEffect(() => {
    const load = async () => {
      try {
        const status = await window.api.health.status()
        if (!status?.checks) return
        const relevant = status.checks.filter(
          (c) =>
            c.severity === 'red' &&
            BANNER_CHECK_IDS.some((id) => c.id.startsWith(id))
        )
        setChecks(relevant)
      } catch {
        // health status unavailable; don't show banner
        setChecks([])
      }
    }
    load()
    const interval = setInterval(load, 60_000)
    return () => clearInterval(interval)
  }, [])

  if (!checks.length) return null

  return (
    <div className="mb-4 rounded-lg border border-red-900 bg-red-950 p-4">
      <p className="text-sm font-medium text-red-300 mb-2">Health alerts:</p>
      <ul className="space-y-1">
        {checks.map((c) => (
          <li key={c.id} className="text-xs text-red-200">
            {c.detail}
          </li>
        ))}
      </ul>
    </div>
  )
}
