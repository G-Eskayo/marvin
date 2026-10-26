import { deriveStageStrip, formatElapsed as formatElapsedMs, STAGE_LABEL } from '../lib/stage_strip.js'
import { useState } from 'react'

// Visual styling for stage segment states.
const SEGMENT_CLASS = {
  pending: 'bg-neutral-800 text-neutral-400',
  passed: 'bg-emerald-950 text-emerald-300',
  failed: 'bg-red-950 text-red-300',
  running: 'bg-blue-950 text-blue-300',
  stalled: 'bg-amber-950 text-amber-300',
  'needs-rebase': 'bg-amber-950 text-amber-300',
  skipped: 'bg-neutral-700 text-neutral-500'
}

const SEGMENT_ICON = {
  pending: '◌',
  passed: '✓',
  failed: '✕',
  running: '◐',
  stalled: '⏱',
  'needs-rebase': '⟳',
  skipped: '∅'
}

// Horizontal stage strip: one pill per stage, click-through to scroll in PipelineHistory.
// When a stage is running, shows live elapsed time.
function Segment({ segment, onClick, isRunning }) {
  const [hoverDetail, setHoverDetail] = useState(false)
  const displayStatus = segment.status === 'needs-rebase' ? 'needs rebase' : segment.status
  const tooltip = [
    `${STAGE_LABEL[segment.stage]} · ${displayStatus}`,
    segment.remediation && `Remediation: ${segment.remediation}`,
    segment.detail && `${segment.detail.slice(0, 100)}${segment.detail.length > 100 ? '…' : ''}`
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <button
      onClick={() => onClick(segment.stage)}
      onMouseEnter={() => setHoverDetail(true)}
      onMouseLeave={() => setHoverDetail(false)}
      className={`relative inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-all ${SEGMENT_CLASS[segment.status]} hover:brightness-110`}
      title={tooltip}
    >
      <span className="text-[10px]">{SEGMENT_ICON[segment.status]}</span>
      <span>{STAGE_LABEL[segment.stage]}</span>
      {isRunning && segment.elapsed !== null && (
        <span className="text-[10px] text-opacity-70">{formatElapsedMs(segment.elapsed)}</span>
      )}
      {hoverDetail && segment.remediation && (
        <div className="absolute bottom-full left-0 mb-1 whitespace-nowrap rounded bg-neutral-900 px-2 py-1 text-xs text-neutral-200 shadow-lg">
          {segment.remediation.slice(0, 80)}
          {segment.remediation.length > 80 ? '…' : ''}
        </div>
      )}
    </button>
  )
}

// Main component: render the stage strip and handle navigation to history.
export default function StageStrip({
  events = [],
  liveOverlay = null,
  onSegmentClick = null,
  historyRef = null
}) {
  const segments = deriveStageStrip(events, { liveOverlay })

  function scrollToStage(stageName) {
    if (!historyRef?.current) return
    const stageElement = historyRef.current.querySelector(`[data-stage="${stageName}"]`)
    if (stageElement) {
      stageElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      stageElement.classList.add('ring-2', 'ring-blue-500')
      setTimeout(() => stageElement.classList.remove('ring-2', 'ring-blue-500'), 2000)
    }
  }

  function handleSegmentClick(stageName) {
    onSegmentClick?.(stageName)
    scrollToStage(stageName)
  }

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      {segments.map((segment) => (
        <Segment
          key={segment.stage}
          segment={segment}
          onClick={handleSegmentClick}
          isRunning={segment.status === 'running'}
        />
      ))}
    </div>
  )
}
