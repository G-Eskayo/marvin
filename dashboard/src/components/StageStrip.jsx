import { useState } from 'react'
import { STAGE_LABEL } from '../lib/stage_names.js'

const STATUS_STYLE = {
  started: 'bg-neutral-700 text-neutral-300',
  passed: 'bg-emerald-900 text-emerald-200',
  failed: 'bg-red-900 text-red-200'
}

const STATUS_ICON = {
  started: '⏳',
  passed: '✓',
  failed: '✗'
}

export default function StageStrip({ strip, onStageClick = null }) {
  const [hoveredStage, setHoveredStage] = useState(null)

  return (
    <div className="flex items-center gap-1">
      {strip.map((item) => (
        <div key={item.stage} className="relative">
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => {
              e.stopPropagation()
              onStageClick?.(item.stage)
            }}
            onKeyDown={(e) => {
              e.stopPropagation()
              if (e.key === 'Enter' || e.key === ' ') onStageClick?.(item.stage)
            }}
            onMouseEnter={() => setHoveredStage(item.stage)}
            onMouseLeave={() => setHoveredStage(null)}
            className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-all ${STATUS_STYLE[item.status] || 'bg-neutral-800 text-neutral-400'} ${onStageClick ? 'cursor-pointer hover:brightness-125' : ''}`}
            title={`${STAGE_LABEL[item.stage]} (${item.status})`}
          >
            <span>{STATUS_ICON[item.status]}</span>
            <span>{STAGE_LABEL[item.stage]}</span>
            {item.needsRebase && <span className="ml-0.5">⚠</span>}
            {item.liveStatus === 'stalled' && <span className="ml-0.5 animate-pulse">●</span>}
          </span>

          {hoveredStage === item.stage && (
            <div className="absolute top-full left-1/2 -translate-x-1/2 mt-1 rounded bg-neutral-800 px-2 py-1 text-xs text-neutral-300 whitespace-nowrap z-50 border border-neutral-700">
              <div>{item.when}</div>
              <div>{item.machine}</div>
              <div>{item.money}</div>
              {item.remediation && (
                <div className="mt-1 border-t border-neutral-700 pt-1 text-amber-300">
                  {item.remediation.slice(0, 50)}
                  {item.remediation.length > 50 ? '…' : ''}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
