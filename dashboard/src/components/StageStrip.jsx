import { STAGE_LABEL } from '../lib/stage_labels.js'

function StageSegment({ segment }) {
  const statusColors = {
    passed: 'bg-emerald-600',
    failed: 'bg-red-600',
    started: 'bg-blue-500',
    pending: 'bg-neutral-700'
  }

  const statusClass = statusColors[segment.status] || statusColors.pending
  const isStalled = segment.isStalled
  const isRunning = segment.isRunning

  const tooltipText = [
    STAGE_LABEL[segment.stage] || segment.stage,
    segment.status,
    segment.elapsedLabel,
    segment.machine,
    segment.costUsd ? `$${segment.costUsd.toFixed(2)}` : null,
    segment.remediationLabel ? `Remediation: ${segment.remediationLabel}` : null,
    segment.remediation || segment.detail ? `${segment.remediation || segment.detail}` : null
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <div
      className="relative flex-shrink-0"
      title={tooltipText}
    >
      <div
        className={`w-6 h-6 rounded-sm transition-all ${statusClass} ${
          isStalled ? 'ring-2 ring-yellow-300 ring-offset-1' : ''
        }`}
      />
      {isRunning && (
        <div className="absolute inset-0 rounded-sm animate-pulse pointer-events-none">
          <div className="w-6 h-6 rounded-sm bg-blue-400 opacity-50" />
        </div>
      )}
    </div>
  )
}

export default function StageStrip({ segments }) {
  if (!segments || segments.length === 0) return null

  return (
    <div className="flex gap-1 items-center">
      {segments.map((segment, i) => (
        <StageSegment key={i} segment={segment} />
      ))}
    </div>
  )
}
