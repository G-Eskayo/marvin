import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

const METRICS = [
  { key: 'disk_pct', label: 'Disk free', unit: '%', higherIsBetter: true, color: '#60a5fa' },
  { key: 'mem_pressure', label: 'Memory pressure', unit: '%', higherIsBetter: false, color: '#f87171' },
  { key: 'swap_pct', label: 'Swap usage', unit: '%', higherIsBetter: false, color: '#fbbf24' },
  { key: 'cpu_pct', label: 'CPU usage', unit: '%', higherIsBetter: false, color: '#34d399' },
  { key: 'gpu_pct', label: 'GPU usage', unit: '%', higherIsBetter: false, color: '#a78bfa' },
]

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

function CustomTooltip({ active, payload }) {
  if (active && payload && payload.length) {
    const data = payload[0].payload
    return (
      <div className="rounded border border-neutral-600 bg-neutral-800 p-2 text-xs text-neutral-100">
        <p>{formatTime(data.timestamp_iso)}</p>
        <p className="font-semibold">
          {payload[0].value}%
        </p>
      </div>
    )
  }
  return null
}

function Sparkline({ name, metric, data, color, higherIsBetter }) {
  const values = data
    .map(d => d[metric])
    .filter(v => v !== null && v !== undefined)

  if (values.length === 0) {
    return (
      <div className="rounded border border-neutral-800 bg-neutral-900 p-3">
        <h4 className="text-xs text-neutral-400">{name}</h4>
        <p className="font-mono text-sm text-neutral-500 mt-2">No data</p>
      </div>
    )
  }

  const latest = values[values.length - 1]
  const trendUp = values.length >= 2 && values[values.length - 1] > values[0]
  const trendGood = higherIsBetter ? trendUp : !trendUp

  return (
    <div className="rounded border border-neutral-800 bg-neutral-900 p-3">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-mono text-neutral-300">{name}</h4>
        <span className={`text-xs font-mono ${
          latest < 20 ? 'text-green-400' :
          latest < 50 ? 'text-amber-400' :
          'text-red-400'
        }`}>
          {latest.toFixed(0)}%
        </span>
      </div>
      {values.length >= 2 && (
        <ResponsiveContainer width="100%" height={60}>
          <LineChart data={data.filter(d => d[metric] !== null)}>
            <XAxis dataKey="timestamp_iso" hide />
            <YAxis hide domain={[0, 100]} />
            <Tooltip content={<CustomTooltip />} />
            <Line type="monotone" dataKey={metric} stroke={color} strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

function MachineCard({ device, reachability, samples, isLoading, isStale }) {
  const statusColor =
    reachability === 'green' ? 'border-green-500' :
    reachability === 'yellow' ? 'border-amber-500' :
    reachability === 'asleep' ? 'border-neutral-600' :
    'border-red-500'

  const statusLabel =
    reachability === 'asleep' ? 'Asleep' :
    reachability === 'green' ? 'Online' :
    reachability === 'yellow' ? 'Unreachable' :
    'Offline'

  const opacityClass = isStale ? 'opacity-50' : 'opacity-100'

  return (
    <div className={`border-2 ${statusColor} rounded-lg bg-neutral-900 p-4 ${opacityClass}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-mono text-lg font-semibold text-white">{device}</h3>
        <span className={`text-xs px-2 py-1 rounded font-mono ${
          reachability === 'green' ? 'bg-green-900 text-green-200' :
          reachability === 'asleep' ? 'bg-neutral-700 text-neutral-300' :
          reachability === 'yellow' ? 'bg-amber-900 text-amber-200' :
          'bg-red-900 text-red-200'
        }`}>
          {statusLabel}
        </span>
      </div>

      {isLoading && <p className="text-sm text-neutral-500">Loading…</p>}
      {!isLoading && !samples && <p className="text-sm text-neutral-500">Not yet monitored</p>}
      {!isLoading && samples && samples.length === 0 && <p className="text-sm text-neutral-500">No samples yet</p>}

      {!isLoading && samples && samples.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {METRICS.map(m => (
            <Sparkline
              key={m.key}
              name={m.label}
              metric={m.key}
              data={samples}
              color={m.color}
              higherIsBetter={m.higherIsBetter}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default function ResourcesPanel({ machines, reachability, onClose }) {
  const [samples, setSamples] = useState({})
  const [loading, setLoading] = useState({})
  const [stale, setStale] = useState({})

  useEffect(() => {
    let cancelled = false

    async function loadSamples() {
      const newSamples = {}
      const newLoading = {}
      const newStale = {}

      for (const device of machines) {
        newLoading[device] = true
        try {
          const data = await window.api.resources.samples(device)
          if (!cancelled) {
            newSamples[device] = data.samples || []
            newStale[device] = data.isStale || false
          }
        } catch (err) {
          if (!cancelled) {
            newSamples[device] = []
          }
        } finally {
          newLoading[device] = false
        }
      }

      if (!cancelled) {
        setSamples(newSamples)
        setLoading(newLoading)
        setStale(newStale)
      }
    }

    loadSamples()

    // Refresh every 30 seconds (matching the collector interval)
    const interval = setInterval(loadSamples, 30000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [machines])

  return (
    <div className="p-6">
      {onClose && (
        <button onClick={onClose} className="mb-4 text-sm text-neutral-400 hover:text-neutral-200">
          ← Back
        </button>
      )}
      <h2 className="mb-4 font-mono text-lg font-semibold text-white">Machine Resources (24h)</h2>
      <p className="mb-6 text-sm text-neutral-400">
        Live metrics from each machine, refreshing every 30 seconds.
        Asleep machines show last-known values at 50% opacity.
      </p>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {machines.map(device => (
          <MachineCard
            key={device}
            device={device}
            reachability={reachability[device] || 'yellow'}
            samples={samples[device]}
            isLoading={loading[device]}
            isStale={stale[device]}
          />
        ))}
      </div>
    </div>
  )
}
