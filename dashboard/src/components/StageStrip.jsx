import { deriveSegments } from '../lib/stage_strip.js'

export function StageStrip({ stages, rebase, isLiveNow, now, onStageClick }) {
  const segments = deriveSegments(stages, { rebase, isLiveNow, now })

  const statusIcon = {
    passed: '✓',
    failed: '✗',
    started: '⊚',
    stalled: '·',
    pending: '◦',
  }

  const statusColor = {
    passed: 'text-emerald-500',
    failed: 'text-red-500',
    started: 'animate-pulse text-blue-500',
    stalled: 'text-amber-500',
    pending: 'text-neutral-500',
  }

  return (
    <div className="flex items-center gap-1 mt-2 text-xs">
      {segments.map((seg, i) => (
        <div
          key={i}
          role={onStageClick ? 'button' : undefined}
          tabIndex={onStageClick ? 0 : undefined}
          onClick={() => onStageClick?.(seg.key)}
          onKeyDown={(e) => e.key === 'Enter' && onStageClick?.(seg.key)}
          title={`${seg.label}: ${seg.status}${seg.message ? ' · ' + seg.message : ''}${seg.remediation ? ' · ' + seg.remediation : ''} @ ${new Date(seg.timestamp).toLocaleTimeString()}`}
          className={`inline-flex items-center gap-0.5 rounded px-1 py-0.5 ${
            seg.status === 'failed'
              ? 'bg-red-950 text-red-300'
              : seg.status === 'passed'
                ? 'bg-emerald-950 text-emerald-300'
                : seg.status === 'started'
                  ? 'bg-blue-950 text-blue-300'
                  : seg.status === 'stalled'
                    ? 'bg-amber-950 text-amber-300'
                    : 'bg-neutral-800 text-neutral-400'
          } ${onStageClick ? 'cursor-pointer hover:brightness-125' : ''}`}
        >
          <span className={statusColor[seg.status]}>{statusIcon[seg.status]}</span>
          <span className="whitespace-nowrap">{seg.label}</span>
        </div>
      ))}
    </div>
  )
}
