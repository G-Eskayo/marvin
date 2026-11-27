// Pure function for Health tab dot status (mirrors pr_fetch_status.js's reviewDotStatus pattern).
// Takes health status and renders {dot, note} for the tab indicator.

function ago(s) {
  if (s == null) return 'age unknown'
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 2 * 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} days ago`
}

export function healthDotStatus({ overall, copy, checksCount } = {}, now = Date.now()) {
  // Unknown severity: treat as warning, never green
  const isValidSeverity = ['green', 'yellow', 'red'].includes(overall)
  if (!isValidSeverity) {
    return { dot: 'grey', note: 'Overall: unrecognized' }
  }

  // Empty or partial snapshot: never green
  if (checksCount == null || checksCount === 0) {
    return { dot: 'yellow', note: 'Overall: unknown' }
  }

  // Check for stale or future-dated snapshot (future_clock decision: treat as untrustworthy)
  const untrustworthy = copy?.stale || copy?.future
  if (untrustworthy) {
    const reason = copy?.future ? 'future-dated' : 'frozen sweep'
    const ageStr = ago(copy?.ageS)
    return { dot: 'yellow', note: `Overall: ${overall} · ${reason} · ${ageStr}` }
  }

  // Green and fresh: show today's status
  if (overall === 'green') {
    return { dot: 'green', note: 'Overall: healthy' }
  }

  // Yellow or red: show the level (never green)
  return { dot: overall, note: `Overall: ${overall === 'yellow' ? 'degraded' : 'critical'}` }
}
