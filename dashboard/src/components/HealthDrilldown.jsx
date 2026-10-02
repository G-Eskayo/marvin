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

export default function HealthDrilldown({ check, onBack }) {
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
    </div>
  )
}
