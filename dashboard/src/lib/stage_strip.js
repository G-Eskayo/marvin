// Pure function: merges ticket_stages events with refusal_log entries to derive the stage-strip visualization.
// Returns { segments: [{stage, status, icon, color, refusal?, stalled?, machine, costUsd, timestamp, elapsedMinutes}], totalCostUsd }

const REFUSAL_REASONS = {
  MAIN_RED: 'main was failing',
  GATE_TESTS_FAILED: 'tests failed',
  GATE_INFRA: 'the build machine failed',
  OUT_OF_ORDER: 'merge another PR first',
  CI_PENDING: 'checks still running',
  CI_FAILED: 'GitHub checks failed',
  SENT_BACK: 'sent back for rework',
  WRONG_BASE: 'wrong base branch',
  NO_UI_EVIDENCE: 'needed screenshots',
  DECISIONS_PENDING: 'decisions not answered',
  NO_MERGE_PROFILE: 'this project can\'t merge from the dashboard',
  MERGE_REFUSED: 'GitHub refused the merge',
  REBASE_CONFLICT: 'conflicts after rebase'
}

const plainReason = (code) => REFUSAL_REASONS[code] || code

const STAGE_LABEL = {
  claimed: 'Claimed',
  planning: 'Planning',
  executing: 'Executing',
  verifying: 'Verifying',
  gate: 'Merge gate',
  mutation: 'Mutation',
  merging: 'Merging',
  versioning: 'Versioning',
  rebuilding: 'Rebuilding',
  done: 'Done'
}

export function deriveStageStrip({ events = [], refusals = [], labels = [], now = Date.now, stallMinutes = 30 }) {
  if (!events.length) return { segments: [], totalCostUsd: 0 }

  // Sort refusals by timestamp for chronological matching.
  const sortedRefusals = [...(refusals || [])].sort((a, b) => (a.t || '').localeCompare(b.t || ''))

  // Check if this ticket needs a human (blocked/waiting for rework).
  const waitingOnHuman = labels.includes('needs-reengagement')

  // Build segments from events, linking refusals where applicable.
  const segments = []
  let totalCost = 0
  let refusalIndex = 0

  for (const e of events) {
    const elapsedMs = e.status === 'started' ? now() - Date.parse(e.timestamp) : 0
    const elapsedMinutes = Math.floor(elapsedMs / 60000)
    const stalled = e.status === 'started' && elapsedMinutes >= stallMinutes
    const costUsd = e.cost_usd || 0
    totalCost += costUsd

    let icon = '●'
    let color = 'gray'

    if (e.status === 'passed') {
      icon = '✓'
      color = 'emerald'
    } else if (e.status === 'failed') {
      icon = '✕'
      color = 'red'
    } else if (e.status === 'started') {
      icon = stalled ? '⏱' : '●'
      color = stalled ? 'amber' : 'blue'
    }

    // If this ticket is waiting on a human and there's a failed stage, mark it as needing them.
    if (waitingOnHuman && e.status === 'failed') {
      icon = '👤'
      color = 'gray'
    }

    // Look for a matching refusal (by timestamp proximity).
    // Refusals are tied to stages by timestamp order: find the next refusal after this event.
    let matchedRefusal = null
    if (refusalIndex < sortedRefusals.length) {
      const nextRefusal = sortedRefusals[refusalIndex]
      const refusalTime = Date.parse(nextRefusal.t || '')
      const eventTime = Date.parse(e.timestamp || '')
      // Match if the refusal is within a reasonable window after this event (up to 1 hour).
      if (refusalTime >= eventTime && refusalTime - eventTime <= 3600000) {
        matchedRefusal = { code: nextRefusal.code, reason: plainReason(nextRefusal.code), message: nextRefusal.message || '' }
        refusalIndex++
        color = 'red'
      }
    }

    const segment = {
      stage: e.stage,
      label: STAGE_LABEL[e.stage] || e.stage,
      status: e.status,
      icon,
      color,
      machine: e.machine,
      costUsd,
      timestamp: e.timestamp,
      elapsedMinutes: elapsedMinutes > 0 ? elapsedMinutes : undefined
    }

    if (stalled) segment.stalled = true
    if (matchedRefusal) segment.refusal = matchedRefusal

    segments.push(segment)
  }

  return { segments, totalCostUsd: Math.round(totalCost * 100) / 100 }
}
