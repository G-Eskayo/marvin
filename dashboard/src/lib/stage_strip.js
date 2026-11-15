// Pure derivation function for pipeline stage visibility: events → display segments.
// No React, no DOM. Used by both StageStrip.jsx (dashboard) and future MARVIN Mobile renderer.
// Shared with ../components/PipelineHistory.jsx via exported helpers.

import { plainLabel, remediationFor, needsYouFor, REMEDIATION_BY_CODE as REMEDIATION_TABLE } from '../../electron/main/failure.js'

// Canonical stage order from ticket_stages.js' VALID_STAGES, in pipeline-execution order.
const TERMINAL_STAGE_ORDER = ['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging', 'versioning', 'rebuilding', 'done']

// Display labels matching the issue's example wording (plan/build/verify/PR/order/gate/merge, mutations appended).
// Exported so PipelineHistory and StageStrip both import from here (not duplicated in ProjectBoard.jsx).
export const STAGE_LABEL = {
  claimed: 'Claimed',
  planning: 'Plan',
  executing: 'Build',
  verifying: 'Verify',
  gate: 'Merge gate',
  merging: 'PR',
  versioning: 'Versioning',
  rebuilding: 'Rebuilding',
  done: 'Done'
}

export const money = (usd) => (usd ? `$${usd.toFixed(usd < 0.01 ? 4 : 2)}` : '$0.00')
export const when = (iso) => {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return iso
  }
}

// Default stall thresholds: per-stage (option C from decisions).
// A stage with no event for longer than its threshold is stalled.
// gate gets 35 min (just under GATE_TIMEOUT_MS's 40 min), others default to 10 min.
const STALL_THRESHOLD_MS = {
  claimed: 10 * 60_000,
  planning: 10 * 60_000,
  executing: 10 * 60_000,
  verifying: 10 * 60_000,
  gate: 35 * 60_000,
  merging: 10 * 60_000,
  versioning: 10 * 60_000,
  rebuilding: 10 * 60_000,
  done: 10 * 60_000
}

// Tolerant extraction of a refusal code from a detail string.
// Handles shapes: "OUT_OF_ORDER: ...", "CI_FAILED: ...", "REBASE_CONFLICT: ...", or bare message.
// Returns null if no code is found, never throws.
export function extractCode(detail) {
  if (!detail) return null
  const match = detail.match(/^([A-Z_]+):\s/)
  return match ? match[1] : null
}

// Re-export from the canonical table in failure.js for backwards compatibility.
export const REMEDIATION_BY_CODE = REMEDIATION_TABLE
export { remediationFor }

// Derive the status of a stage given its most-recent event(s) and live overlay.
// status: 'pending' (no event), 'started' (started, not yet passed/failed), 'passed', 'failed', 'running', 'stalled', 'skipped'
// The only positive signal from live is isLiveNow === true (this machine running now); false never means "definitely not running" (could be another machine).
function deriveStatus(events, stage, liveOverlay) {
  const stageEvents = events.filter((e) => e.stage === stage)
  if (stageEvents.length === 0) return 'pending'

  const latest = stageEvents[stageEvents.length - 1]

  // If this stage has a passed/failed event, that's terminal.
  if (latest.status === 'passed') return 'passed'
  if (latest.status === 'failed') return 'failed'

  // latest.status === 'started': check if it's still running or stalled.
  if (!latest.timestamp) return 'pending' // malformed, degrade gracefully

  const elapsed = Date.now() - new Date(latest.timestamp).getTime()
  const threshold = STALL_THRESHOLD_MS[stage] || STALL_THRESHOLD_MS.claimed

  // isLiveNow is a positive signal only: true means "definitely running on this machine right now".
  // false means "not running on this machine", which does NOT prove it's stalled (could be another machine).
  // So: if isLiveNow is true, it's running. If false, we must check elapsed time.
  if (liveOverlay?.isLiveNow === true) return 'running'

  // No positive signal from liveOverlay: use elapsed time to decide.
  if (elapsed > threshold) return 'stalled'
  return 'running'
}

// Main derivation: events → segments ready for display.
// opts: { liveOverlay?, now?, stallThreshold? } — mostly for testing; live code usually omits them.
// liveOverlay shape: { isLiveNow, checks?, conflicts?, sentBack?, rework?, waitingOn?, baseProblem?, rebase? }
//   (from mr_review.js's listPipelinePrs, or a ticket's claim label and local machine identity).
export function deriveStageStrip(events = [], opts = {}) {
  const liveOverlay = opts.liveOverlay || {}
  const now = opts.now || Date.now()
  const thresholds = opts.stallThreshold ? { ...STALL_THRESHOLD_MS, ...opts.stallThreshold } : STALL_THRESHOLD_MS

  const segments = []

  for (const stage of TERMINAL_STAGE_ORDER) {
    const status = deriveStatus(events, stage, liveOverlay)
    const stageEvents = events.filter((e) => e.stage === stage)

    // For failed stages, extract the code and remediation from the latest event's detail.
    let code = null
    let remediation = null
    let cause = null
    if (status === 'failed' && stageEvents.length > 0) {
      const latest = stageEvents[stageEvents.length - 1]
      code = extractCode(latest.detail)
      remediation = remediationFor(code)
      // What the gate knew went wrong ("The Mac mini's disk is nearly full (...)"), after the code (2026-10-28).
      if (code) cause = String(latest.detail).slice(code.length + 1).trim() || null
    }

    // Special case: gate-stage failure with REBASE_CONFLICT code becomes a distinct "needs rebase" state.
    let displayStatus = status
    if (stage === 'gate' && status === 'failed' && code === 'REBASE_CONFLICT') {
      displayStatus = 'needs-rebase'
    }

    segments.push({
      stage,
      label: STAGE_LABEL[stage] || stage,
      status: displayStatus,
      code,
      cause,
      remediation,
      elapsed: status === 'running' && stageEvents.length > 0 ? now - new Date(stageEvents[stageEvents.length - 1].timestamp).getTime() : null,
      detail: stageEvents.length > 0 ? stageEvents[stageEvents.length - 1].detail : ''
    })
  }

  return segments
}

// Elapsed time formatting: e.g. "2m 34s", "1h 5m", for display in running segments.
export function formatElapsed(ms) {
  if (!ms || ms < 0) return '0s'
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)

  if (hours > 0) {
    return `${hours}h ${minutes % 60}m`
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`
  }
  return `${seconds}s`
}
