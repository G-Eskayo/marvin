import { ageText } from './saved_state.js'

// What the Docs tab keeps after docs:repos or docs:refresh: { generated_at, repos: [...] }, with repos
// always an array so the project list can render even when the main process answers oddly.
export function docsCacheFrom(result) {
  if (Array.isArray(result)) return { generated_at: null, repos: result }
  const repos = Array.isArray(result?.repos) ? result.repos : []
  return { generated_at: result?.generated_at ?? null, repos }
}

// The saved-copy part of the Docs source line for a GitHub-only project (#565, mock-ups ticket-403-f-5a/5b): its age
// while the one open-time check runs, "up to date" once GitHub answered, and the age again when it could not ask.
// `dot` picks the marker: 'checking' (pulsing blue), 'ok' (green), 'stale' (grey).
export function savedCopyLine(copy, status, now = Date.now()) {
  const at = Number(copy?.checkedAt) || Number(copy?.savedAt) || null
  const age = at ? `, ${ageText(at, now).replace(/^updated /, '')}` : ''
  if (status === 'checking') return { text: `from GitHub${age} · checking…`, dot: 'checking' }
  if (status === 'unchanged' || status === 'changed') return { text: 'from GitHub · up to date', dot: 'ok' }
  if (status === 'offline' || status === 'skipped') return { text: `from GitHub${age} · could not check`, dot: 'stale' }
  return null
}
