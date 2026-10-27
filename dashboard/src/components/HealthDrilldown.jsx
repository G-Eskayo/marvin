import { useState } from 'react'

const SEVERITY_LABEL = {
  red: 'Broken',
  yellow: 'Degraded',
  green: 'Healthy',
  asleep: 'Asleep (lid closed or away)',
  unmonitored: 'Unmonitored'
}

function formatTimestamp(iso) {
  if (!iso) return 'never'
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

// marvin#691: the one check you can act on from here. The rebuild runs the same refresh the git hooks run.
function RebuildGraphButton({ onRebuildGraph }) {
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState(null)
  async function run() {
    setBusy(true)
    setFailure(null)
    try {
      const r = await onRebuildGraph()
      if (r && r.ok === false) setFailure(r.output || 'rebuild failed')
    } catch (err) {
      setFailure(String(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="mt-4">
      <button
        onClick={run}
        disabled={busy}
        className="rounded-md border border-neutral-700 bg-neutral-800 px-3 py-1.5 text-sm text-neutral-200 hover:bg-neutral-700 disabled:opacity-50"
      >
        {busy ? 'Rebuilding…' : 'Rebuild graph now'}
      </button>
      {failure && <p className="mt-2 whitespace-pre-wrap font-mono text-xs text-red-400">{failure}</p>}
    </div>
  )
}

export default function HealthDrilldown({ check, onBack, onRebuildGraph }) {
  return (
    <div className="p-6">
      <button onClick={onBack} className="mb-4 text-sm text-neutral-400 hover:text-neutral-200">
        ← Back to all checks
      </button>
      <h2 className="mb-1 font-mono text-lg font-semibold text-white">{check.label}</h2>
      <p className="mb-4 text-xs text-neutral-500">{check.id}</p>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-sm">
        <dt className="text-neutral-500">Status</dt>
        <dd className="text-neutral-200">{SEVERITY_LABEL[check.severity] ?? check.severity}</dd>

        <dt className="text-neutral-500">Last checked</dt>
        <dd className="text-neutral-200">{formatTimestamp(check.checked_at)}</dd>

        {check.value !== null && check.value !== undefined && (
          <>
            <dt className="text-neutral-500">Value</dt>
            <dd className="font-mono text-neutral-200">{check.value}</dd>
          </>
        )}
      </dl>

      <div className="mt-4 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h3 className="mb-2 text-xs uppercase tracking-wide text-neutral-500">Detail</h3>
        <p className="whitespace-pre-wrap font-mono text-sm text-neutral-200">{check.detail}</p>
      </div>

      {check.id === 'graphify:fresh' && onRebuildGraph && <RebuildGraphButton onRebuildGraph={onRebuildGraph} />}
    </div>
  )
}
