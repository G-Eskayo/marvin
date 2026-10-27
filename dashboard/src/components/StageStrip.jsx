function formatTime(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

const COLOR_CLASS = {
  emerald: 'text-emerald-400 hover:text-emerald-300',
  blue: 'text-blue-400 hover:text-blue-300',
  amber: 'text-amber-400 hover:text-amber-300',
  red: 'text-red-400 hover:text-red-300',
  gray: 'text-neutral-400 hover:text-neutral-300'
}

export default function StageStrip({ segments = [], totalCostUsd = 0, onStageClick = () => {} }) {
  return (
    <div className="flex flex-wrap gap-1 py-2">
      {segments.map((seg, i) => {
        const tooltip = [
          seg.label,
          seg.status,
          `at ${formatTime(seg.timestamp)}`,
          `on ${seg.machine}`,
          `$${seg.costUsd.toFixed(2)}`,
          ...(seg.elapsedMinutes ? [`running ${seg.elapsedMinutes}m`] : []),
          ...(seg.stalled ? ['stalled'] : []),
          ...(seg.refusal ? [`denied: ${seg.refusal.reason}`] : [])
        ].join(' · ')

        return (
          <button
            key={i}
            onClick={() => onStageClick(seg)}
            data-stage={seg.stage}
            title={tooltip}
            className={`inline-flex h-7 w-7 items-center justify-center rounded text-sm font-medium transition-colors ${COLOR_CLASS[seg.color] || COLOR_CLASS.gray} ${seg.color === 'red' ? 'bg-red-950/30' : seg.color === 'amber' ? 'bg-amber-950/30' : seg.color === 'blue' ? 'bg-blue-950/30' : seg.color === 'emerald' ? 'bg-emerald-950/30' : 'bg-neutral-800'}`}
          >
            {seg.icon}
          </button>
        )
      })}
      {totalCostUsd > 0 && (
        <span className="ml-auto flex items-center text-xs text-neutral-500">
          ${totalCostUsd.toFixed(2)}
        </span>
      )}
    </div>
  )
}
