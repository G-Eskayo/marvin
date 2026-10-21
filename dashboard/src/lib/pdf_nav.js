// Pure helpers for the interactive PDF view (G-Eskayo/marvin#402): page jumps, the outline, link safety, find status.

// Links inside a PDF may only open the default browser or mail app: http, https and mailto. Never file:, javascript:,
// data:, or any custom scheme (which could launch an app). Shared by the renderer and re-checked in main.
export function safeExternalUrl(href) {
  if (typeof href !== 'string') return null
  const s = href.trim()
  if (!s || /[\u0000-\u001f]/.test(s)) return null
  let u
  try {
    u = new URL(s)
  } catch {
    return null
  }
  if (!['http:', 'https:', 'mailto:'].includes(u.protocol)) return null
  if ((u.protocol === 'http:' || u.protocol === 'https:') && !u.hostname) return null
  return u.href
}

// "page [ n ] of N": a whole number in range, or null (the input is then reset to the current page).
export function parsePageInput(value, total) {
  const s = String(value ?? '').trim()
  if (!/^\d{1,7}$/.test(s)) return null
  const n = Number(s)
  return n >= 1 && n <= total ? n : null
}

export const clampPage = (n, total) => Math.min(Math.max(1, Math.round(Number(n) || 1)), Math.max(1, total || 1))

// pdf.js outline → [{ title, dest, url, items }] with depth limits, so a hostile, deeply nested outline can't hang it.
export function normalizeOutline(items, depth = 0, budget = { left: 2000 }) {
  if (!Array.isArray(items) || depth > 12) return []
  const out = []
  for (const it of items) {
    if (budget.left-- <= 0) break
    out.push({
      title: String(it?.title || '').trim() || 'Untitled',
      dest: it?.dest ?? null,
      url: safeExternalUrl(it?.url),
      items: normalizeOutline(it?.items, depth + 1, budget)
    })
  }
  return out
}

// The find bar's status line from pdf.js's match counts.
export function findStatus({ query, total, current } = {}) {
  if (!query) return ''
  if (!total) return 'No matches'
  return `${Math.max(1, current || 1)} of ${total} match${total === 1 ? '' : 'es'}`
}
