// Pure helpers for the Portfolio tab -- kept out of the React component so the logic is testable.

export function groupFindingsByRule(findings, filterText = '') {
  const needle = String(filterText || '').trim().toLowerCase()
  const groups = new Map()
  for (const f of findings || []) {
    if (needle && !`${f.page} ${f.rule} ${f.detail}`.toLowerCase().includes(needle)) continue
    if (!groups.has(f.rule)) groups.set(f.rule, [])
    groups.get(f.rule).push(f)
  }
  return [...groups.entries()].map(([rule, items]) => ({ rule, items })).sort((a, b) => b.items.length - a.items.length)
}

export function parseRulesText(text) {
  const t = String(text ?? '').trim()
  if (!t) return { ok: true, value: {} }
  let value
  try {
    value = JSON.parse(t)
  } catch (err) {
    return { ok: false, error: `Not valid JSON: ${err.message}` }
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return { ok: false, error: 'Rules must be a JSON object' }
  }
  return { ok: true, value }
}

// A component previews inside a sandboxed iframe using the REAL dev site's stylesheets (the
// head comes from the main process), so a button looks exactly as it will on a page.
export function previewDocument(html, head) {
  return `<!doctype html><html><head><meta charset="utf-8">${head || ''}</head><body style="margin:0;padding:16px;background:#fff"><div style="max-width:340px">${html}</div></body></html>`
}

export function nextComponentName(typed) {
  return String(typed || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
}

export function formatRunTime(iso) {
  if (!iso) return 'never'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'unknown' : d.toLocaleString()
}
