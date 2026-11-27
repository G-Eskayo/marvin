// Health verdict display logic (#899), kept pure so it can be tested without a DOM.
// One source of truth for "can this verdict be trusted right now" across HealthDashboard and App.jsx tab dot.

function ageWords(ageS) {
  if (ageS == null || !Number.isFinite(ageS)) return 'age unknown'
  const s = Math.max(0, ageS)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 2 * 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} days ago`
}

function ageDuration(ageS) {
  if (ageS == null || !Number.isFinite(ageS)) return 'age unknown'
  const s = Math.max(0, ageS)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min`
  if (s < 2 * 86400) return `${Math.floor(s / 3600)} h`
  return `${Math.floor(s / 86400)} days`
}

export function verdictLine(overall, copy) {
  const VALID_SEVERITIES = new Set(['red', 'yellow', 'green'])
  const severity = VALID_SEVERITIES.has(overall) ? overall : 'yellow'

  if (!copy || typeof copy !== 'object') {
    return { severity: 'yellow', stale: false, text: `degraded · age unknown` }
  }

  const { ageS, stale = false } = copy

  if (stale) {
    return { severity: 'yellow', stale: true, text: `verdict is ${ageDuration(ageS)} old · sweep hasn't run` }
  }

  return { severity, stale: false, text: `${severityPhrase(severity)} · ${ageWords(ageS)}` }
}

function severityPhrase(severity) {
  switch (severity) {
    case 'green': return 'healthy'
    case 'red': return 'something is broken'
    case 'yellow': return 'degraded'
    default: return 'unknown'
  }
}
