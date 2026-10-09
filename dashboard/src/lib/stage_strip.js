import { CORE_STAGES, OPTIONAL_STAGES } from './stage_labels.js'
import { REFUSAL_CODES } from '../../webhook-server/refusal_log.js'

function formatRelativeTime(iso, now = Date.now()) {
  if (!iso) return null
  try {
    const ms = now - Date.parse(iso)
    if (ms < 60000) return 'just now'
    const mins = Math.floor(ms / 60000)
    if (mins < 60) return `${mins}m ago`
    const hours = Math.floor(ms / 3600000)
    if (hours < 24) return `${hours}h ago`
    const days = Math.floor(ms / 86400000)
    return `${days}d ago`
  } catch {
    return iso
  }
}

// Derive stage segments from raw event data, computing elapsed time, remediation, and stall detection.
// Pure function: no side effects, dependency-injected time and live status.
// Returns null if no events, otherwise an array of segment objects (core stages always present as pending if no event).
export function deriveSegments(stages, { isLiveNow, now, stallMinutes = 10 } = {}) {
  if (!stages || Object.keys(stages).length === 0) return null

  const segments = []

  // Walk CORE_STAGES, present pending if no event.
  for (const stage of CORE_STAGES) {
    const events = stages[stage] || []
    segments.push(buildSegment(stage, events, { isLiveNow, now, stallMinutes }))
  }

  // Append OPTIONAL_STAGES only if present (non-empty).
  for (const stage of OPTIONAL_STAGES) {
    const events = stages[stage]
    if (events && events.length > 0) {
      segments.push(buildSegment(stage, events, { isLiveNow, now, stallMinutes }))
    }
  }

  return segments.length > 0 ? segments : null
}

function buildSegment(stage, events, { isLiveNow, now, stallMinutes }) {
  const latestEvent = events.length > 0 ? events[events.length - 1] : null
  const status = latestEvent?.status || 'pending'
  const detail = latestEvent?.detail || ''
  const timestamp = latestEvent?.timestamp ? new Date(latestEvent.timestamp).getTime() : now
  const machine = latestEvent?.machine || 'unknown'
  const costUsd = events.reduce((sum, e) => sum + (e.cost_usd || 0), 0)

  const elapsedMs = Math.max(0, now - timestamp)
  const elapsedLabel = formatRelativeTime(new Date(timestamp).toISOString(), now)

  // Detect if this stage is currently running (live + started + not too old).
  const isStarted = status === 'started'
  const elapsedMinutes = elapsedMs / 60000
  const isStalled = isLiveNow && isStarted && elapsedMinutes >= stallMinutes
  const isRunning = isLiveNow && isStarted && elapsedMinutes < stallMinutes

  // Parse refusal codes and apply relabeling.
  let remediationLabel = null
  let remediation = null

  if (status === 'failed' && detail) {
    const refusalMatch = detail.match(/refused (\w+)/)
    if (refusalMatch) {
      const code = refusalMatch[1]
      if (REFUSAL_CODES.has(code)) {
        if (code === 'OUT_OF_ORDER') {
          remediationLabel = 'Order'
          // OUT_OF_ORDER has no generic remediation; the message is self-describing
        } else {
          remediationLabel = 'Request'
          // Import remediation from RULES if available
          remediation = getRemediationForCode(code)
        }
      }
    }
  }

  return {
    stage,
    status,
    detail,
    timestamp: latestEvent?.timestamp,
    machine,
    costUsd,
    elapsedLabel,
    isRunning,
    isStalled,
    remediationLabel,
    remediation
  }
}

// Map refusal codes to remediation text from failure.js RULES.
function getRemediationForCode(code) {
  const remediations = {
    'WRONG_BASE': 'The PR has the wrong base branch. Rebase onto main and try again.',
    'SENT_BACK': 'The ticket was sent back for rework. Push the fix and re-approve.',
    'CI_PENDING': 'Tests are still running. Approve again when CI finishes.',
    'NO_MERGE_PROFILE': 'No merge profile configured for this project. Add one in the dashboard settings.',
    'MERGE_REFUSED': 'The merge was refused. Check the PR for details.'
  }
  return remediations[code] || null
}
