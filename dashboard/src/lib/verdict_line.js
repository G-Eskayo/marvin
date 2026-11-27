// Pure function for Health tab verdict (mirrors boot_view.js's tone functions).
// Takes health status and renders {tone, text} for the verdict line.

function ago(s) {
  if (s == null) return 'age unknown'
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 2 * 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} days ago`
}

function up(s) {
  return String(s ?? '').toUpperCase()
}

export function verdictLine({ overall, generatedAt, checksCount, copy }, now = Date.now()) {
  // No data at all: unknown
  if (!overall || checksCount === 0) {
    return { tone: 'unknown', text: 'HEALTH UNKNOWN' }
  }

  // Unknown severity: treat as warning, never green
  const isValidSeverity = ['green', 'yellow', 'red'].includes(overall)
  if (!isValidSeverity) {
    return { tone: 'unknown', text: 'HEALTH UNCONFIRMED' }
  }

  // Check for stale or future-dated snapshot (future_clock decision: treat as untrustworthy)
  const untrustworthy = copy?.stale || copy?.future
  if (untrustworthy && generatedAt) {
    const ageStr = up(ago(copy?.ageS))
    const reason = copy?.future ? 'FUTURE-DATED SNAPSHOT' : 'SWEEP FROZEN'
    return { tone: 'stale', text: `${reason} · ${ageStr}` }
  }

  // Green and fresh
  if (overall === 'green' && !untrustworthy) {
    const ageStr = generatedAt && copy?.ageS != null ? ' · ' + up(ago(copy.ageS)) : ''
    return { tone: 'nominal', text: 'HEALTHY' + ageStr }
  }

  // Yellow or red
  if (overall === 'yellow') return { tone: 'issues', text: 'DEGRADED' }
  if (overall === 'red') return { tone: 'issues', text: 'CRITICAL' }

  return { tone: 'unknown', text: 'HEALTH UNCONFIRMED' }
}
