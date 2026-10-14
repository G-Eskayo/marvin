import { useState } from 'react'
import { STAGE_LABEL } from '../lib/stage_strip'

const STATUS_ICONS = {
  passed: '✓',
  failed: '✕',
  started: '◆',
  stalled: '!',
  pending: '·',
  blocked: '⚠'
}

const STATUS_COLORS = {
  passed: 'bg-green-950 text-green-300 border-green-800',
  failed: 'bg-red-950 text-red-300 border-red-800',
  started: 'bg-blue-950 text-blue-300 border-blue-800',
  stalled: 'bg-amber-950 text-amber-300 border-amber-800',
  pending: 'bg-gray-950 text-gray-400 border-gray-800',
  blocked: 'bg-red-950 text-red-300 border-red-800'
}

export function withStopPropagation(e, fn) {
  e.stopPropagation()
  fn()
}

export default function StageStrip({ segments = [], now = Date.now(), onStageClick = null }) {
  const [expanded, setExpanded] = useState(null)

  if (!segments || segments.length === 0) return null

  const handleSegmentClick = (stage) => {
    setExpanded(expanded === stage ? null : stage)
    if (onStageClick) onStageClick(stage)
  }

  const handleKeyDown = (e, stage) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      withStopPropagation(e, () => handleSegmentClick(stage))
    }
  }

  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {segments.map((segment) => {
        const colorClass = STATUS_COLORS[segment.status] || STATUS_COLORS.pending
        const icon = STATUS_ICONS[segment.status] || '·'
        const isExpanded = expanded === segment.stage
        const multiEvent = segment.events && segment.events.length > 1
        const isFailed = segment.status === 'failed' || segment.status === 'blocked'
        const showMessagePanel = (isExpanded && segment.message) || (isFailed && segment.message)

        return (
          <div key={segment.stage} className="flex flex-col gap-1">
            <button
              onClick={(e) => withStopPropagation(e, () => handleSegmentClick(segment.stage))}
              onKeyDown={(e) => handleKeyDown(e, segment.stage)}
              tabIndex={0}
              title={(() => {
                const parts = [segment.label]
                if (segment.message) parts.push(segment.message)
                const lastEvent = segment.events && segment.events.length > 0 ? segment.events[segment.events.length - 1] : null
                if (lastEvent) {
                  if (lastEvent.machine) parts.push(lastEvent.machine)
                  if (lastEvent.timestamp) parts.push(new Date(lastEvent.timestamp).toLocaleString())
                  if (typeof lastEvent.cost_usd === 'number') parts.push(`$${lastEvent.cost_usd.toFixed(2)}`)
                }
                return parts.join(' — ')
              })()}
              className={`rounded border px-2 py-1 text-[10px] font-mono transition-colors ${colorClass} hover:opacity-80 focus:outline-none focus:ring-1 focus:ring-offset-1 focus:ring-offset-neutral-900`}
            >
              <span className="mr-1">{icon}</span>
              <span>{segment.label}</span>
              {multiEvent && <span className="ml-1">({segment.events.length})</span>}
            </button>

            {showMessagePanel && (
              <div className="rounded bg-neutral-800 px-2 py-1 text-[10px] text-neutral-300">
                <p className="mb-1">{segment.message}</p>
                {segment.remediation && (
                  <p className="text-neutral-400">→ {segment.remediation}</p>
                )}
              </div>
            )}

            {isExpanded && multiEvent && (
              <div className="rounded bg-neutral-800 px-2 py-1 text-[10px] text-neutral-300">
                <div className="max-h-32 overflow-y-auto">
                  {segment.events.map((evt, i) => (
                    <div
                      key={i}
                      className="mb-1 border-b border-neutral-700 pb-1 last:border-0 last:mb-0"
                    >
                      <p className="font-mono text-neutral-400">{evt.machine}</p>
                      <p className="text-[9px] text-neutral-500">
                        {new Date(evt.timestamp).toLocaleString()}
                      </p>
                      {typeof evt.cost_usd === 'number' && (
                        <p className="text-[9px] text-neutral-500">
                          ${evt.cost_usd.toFixed(2)}
                        </p>
                      )}
                      {evt.detail && (
                        <p className="mt-0.5 text-neutral-300">
                          {evt.detail.slice(0, 100)}
                          {evt.detail.length > 100 ? '…' : ''}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
