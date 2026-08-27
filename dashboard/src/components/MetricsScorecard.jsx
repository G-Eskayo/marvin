import { useEffect, useState } from 'react'
import SubsystemDrilldown from './SubsystemDrilldown.jsx'

function formatTimestamp(iso) {
  if (!iso) return 'never'
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short'
    })
  } catch {
    return iso
  }
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-neutral-500">
      <p className="text-lg font-medium text-neutral-300">No metrics recorded yet</p>
      <p className="max-w-md text-sm">
        This fills in automatically once MARVIN's background pipeline starts calling{' '}
        <code className="rounded bg-neutral-800 px-1 py-0.5 text-neutral-300">metrics_registry.record()</code>{' '}
        for a subsystem. Nothing is broken — there's just no data yet.
      </p>
    </div>
  )
}

function SubsystemCard({ subsystem, snapshot, onClick }) {
  const metricNames = Object.keys(snapshot.metrics)
  return (
    <button
      onClick={onClick}
      className="flex flex-col gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-left transition-colors hover:border-neutral-600"
    >
      <div className="flex items-center justify-between">
        <h3 className="font-mono text-sm font-semibold text-white">{subsystem}</h3>
        <span className="text-xs text-neutral-500">{metricNames.length} metric{metricNames.length === 1 ? '' : 's'}</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        {metricNames.slice(0, 4).map((name) => (
          <div key={name} className="flex flex-col">
            <dt className="truncate text-xs text-neutral-500">{name}</dt>
            <dd className="font-mono text-neutral-200">{snapshot.metrics[name].value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-neutral-600">Last updated {formatTimestamp(snapshot.timestamp)}</p>
    </button>
  )
}

export default function MetricsScorecard() {
  const [index, setIndex] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    window.api.metrics
      .index()
      .then((result) => {
        if (!cancelled) setIndex(result)
      })
      .catch((err) => {
        if (!cancelled) setError(String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (selected) {
    return <SubsystemDrilldown subsystem={selected} onBack={() => setSelected(null)} />
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center text-red-400">
        Failed to load metrics: {error}
      </div>
    )
  }

  if (index === null) {
    return <div className="flex h-full items-center justify-center text-neutral-500">Loading…</div>
  }

  const subsystems = Object.keys(index).sort()

  if (subsystems.length === 0) {
    return <EmptyState />
  }

  return (
    <div className="p-6">
      <p className="mb-4 text-sm text-neutral-500">
        Whole-system view — {subsystems.length} subsystem{subsystems.length === 1 ? '' : 's'} reporting. Click a
        card for its full trajectory.
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {subsystems.map((subsystem) => (
          <SubsystemCard
            key={subsystem}
            subsystem={subsystem}
            snapshot={index[subsystem]}
            onClick={() => setSelected(subsystem)}
          />
        ))}
      </div>
    </div>
  )
}
