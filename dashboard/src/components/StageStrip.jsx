import { useState } from 'react'

// Visual representation of a ticket's pipeline stage progression.
// Reuses deriveSegments from stage_strip.js for data transformation.
// Shows stage icons with status colors, optional tooltips with machine+cost,
// and click-to-drill-in for multi-event stages.

const STATUS_ICON = {
  passed: '✓',
  failed: '✗',
  started: '→',
  stalled: '⚠',
  pending: '·'
}

const STATUS_CLASS = {
  passed: 'text-green-500',
  failed: 'text-red-500',
  started: 'text-blue-500 animate-pulse',
  stalled: 'text-yellow-600',
  pending: 'text-neutral-500'
}

// Format a timestamp for display
function formatTime(timestamp) {
  if (!timestamp) return ''
  try {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' })
  } catch {
    return ''
  }
}

export default function StageStrip({ segments = [], now = Date.now(), onStageClick = null, rebase = null }) {
  const [expandedStage, setExpandedStage] = useState(null)

  if (!segments || segments.length === 0) return null

  const handleStageClick = (segment) => {
    if (segment.events && segment.events.length > 1) {
      setExpandedStage(expandedStage === segment.stage ? null : segment.stage)
    } else if (onStageClick) {
      onStageClick(segment)
    }
  }

  const handleStageKeyDown = (e, segment) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleStageClick(segment)
    }
  }

  const buildTooltip = (segment) => {
    const parts = []
    if (segment.machine) parts.push(segment.machine)
    if (segment.cost_usd !== undefined && segment.cost_usd !== null) {
      parts.push(`$${segment.cost_usd.toFixed(2)}`)
    }
    if (segment.timestamp) {
      parts.push(formatTime(segment.timestamp))
    }
    return parts.join(' · ')
  }

  return (
    <div className="flex items-center gap-1">
      {segments.map((segment) => {
        const icon = STATUS_ICON[segment.status] || '?'
        const colorClass = STATUS_CLASS[segment.status] || 'text-gray-400'
        const tooltip = buildTooltip(segment)
        const isMultiEvent = segment.events && segment.events.length > 1
        const isExpanded = expandedStage === segment.stage

        return (
          <div key={segment.stage} className="relative group">
            <button
              onClick={() => handleStageClick(segment)}
              onKeyDown={(e) => handleStageKeyDown(e, segment)}
              title={tooltip}
              className={`inline-flex items-center justify-center w-6 h-6 rounded-full border border-current transition-all ${colorClass} ${
                isMultiEvent ? 'cursor-pointer hover:scale-110' : 'cursor-default'
              } ${isExpanded ? 'ring-2 ring-offset-1' : ''}`}
              aria-label={`${segment.label}: ${segment.status}`}
              tabIndex={isMultiEvent ? 0 : -1}
            >
              {icon}
            </button>

            {/* Tooltip with machine and cost */}
            {tooltip && (
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 bg-neutral-800 text-neutral-100 text-xs rounded whitespace-nowrap pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity z-10">
                {tooltip}
              </div>
            )}

            {/* Event list popover for multi-event stages */}
            {isExpanded && isMultiEvent && (
              <div className="absolute left-0 top-full mt-2 bg-neutral-900 border border-neutral-700 rounded p-2 shadow-lg z-20 min-w-48">
                <div className="max-h-48 overflow-y-auto space-y-1">
                  {segment.events.map((event, idx) => (
                    <div key={idx} className="text-xs text-neutral-300 flex justify-between items-start gap-2">
                      <span className="flex-1">
                        <span className={`font-semibold ${STATUS_CLASS[event.status] || 'text-gray-400'}`}>
                          {STATUS_ICON[event.status] || '?'} {event.status}
                        </span>
                        {event.detail && <span className="text-neutral-500 block text-[10px] mt-0.5">{event.detail.slice(0, 60)}</span>}
                      </span>
                      <span className="text-neutral-500 whitespace-nowrap">{formatTime(event.timestamp)}</span>
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
