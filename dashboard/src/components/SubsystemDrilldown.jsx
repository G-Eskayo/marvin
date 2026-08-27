import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'

function formatTick(iso) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

// One small chart per metric rather than one combined chart -- metrics on
// wildly different scales (e.g. a percentage next to a token count) would
// be unreadable stacked on shared axes, and "legible to a lay person" is
// this ticket's own explicit acceptance bar.
function MetricChart({ name, points, higherIsBetter }) {
  const values = points.map((p) => p.value)
  const trendUp = values.length >= 2 && values[values.length - 1] > values[0]
  const trendGood = values.length >= 2 && (higherIsBetter ? trendUp : !trendUp)

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="font-mono text-sm text-neutral-200">{name}</h4>
        {values.length >= 2 && (
          <span className={`text-xs ${trendGood ? 'text-green-400' : 'text-amber-400'}`}>
            {trendUp ? '↑' : '↓'} {higherIsBetter ? '(higher is better)' : '(lower is better)'}
          </span>
        )}
      </div>
      {points.length === 1 ? (
        <p className="font-mono text-2xl text-white">{points[0].value}</p>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={points}>
            <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
            <XAxis dataKey="timestamp" tickFormatter={formatTick} stroke="#525252" fontSize={11} />
            <YAxis stroke="#525252" fontSize={11} width={40} />
            <Tooltip
              labelFormatter={formatTick}
              contentStyle={{ background: '#171717', border: '1px solid #404040', fontSize: 12 }}
            />
            <Line type="monotone" dataKey="value" stroke="#60a5fa" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

export default function SubsystemDrilldown({ subsystem, onBack }) {
  const [history, setHistory] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    window.api.metrics
      .history(subsystem)
      .then((result) => {
        if (!cancelled) setHistory(result)
      })
      .catch((err) => {
        if (!cancelled) setError(String(err))
      })
    return () => {
      cancelled = true
    }
  }, [subsystem])

  return (
    <div className="p-6">
      <button onClick={onBack} className="mb-4 text-sm text-neutral-400 hover:text-neutral-200">
        ← Back to all subsystems
      </button>
      <h2 className="mb-4 font-mono text-lg font-semibold text-white">{subsystem}</h2>

      {error && <p className="text-red-400">Failed to load history: {error}</p>}
      {!error && history === null && <p className="text-neutral-500">Loading…</p>}
      {!error && history !== null && history.length === 0 && (
        <p className="text-neutral-500">No snapshots recorded for this subsystem.</p>
      )}

      {history && history.length > 0 && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {Object.keys(history[history.length - 1].metrics)
            .sort()
            .map((metricName) => {
              const points = history
                .filter((snapshot) => metricName in snapshot.metrics)
                .map((snapshot) => ({
                  timestamp: snapshot.timestamp,
                  value: snapshot.metrics[metricName].value
                }))
              const higherIsBetter = history[history.length - 1].metrics[metricName].higher_is_better
              return (
                <MetricChart key={metricName} name={metricName} points={points} higherIsBetter={higherIsBetter} />
              )
            })}
        </div>
      )}
    </div>
  )
}
