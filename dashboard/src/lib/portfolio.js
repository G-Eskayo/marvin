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
export function previewDocument(html, head, { wide = false } = {}) {
  // Page templates are WordPress/Avada shortcodes that the server expands; in a preview only the real markup
  // inside them should show, not the tokens.
  html = String(html || '').replace(/\[\/?fusion_[a-z_]+[^\]]*\]/g, '')
  return `<!doctype html><html><head><meta charset="utf-8">${head || ''}</head><body style="margin:0;padding:16px;background:#fff"><div style="max-width:${wide ? 'none' : '340px'}">${html}</div></body></html>`
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

// ── template forms (Templates tab) ──────────────────────────────────────────

export const initialData = (template) => Object.fromEntries((template?.fields || []).map((f) => [f.name, f.default ?? '']))

export const fieldInputType = (field) => (field?.type === 'html' ? 'textarea' : field?.type === 'url' ? 'url' : 'text')

export function buildOptions(choices) {
  const out = {}
  for (const [slot, list] of Object.entries(choices || {})) if (list && list.length) out[slot] = list
  return out
}

const KIND_ORDER = ['page', 'component', 'button']
export function groupTemplates(list) {
  return KIND_ORDER.map((kind) => ({ kind, items: (list || []).filter((t) => t.kind === kind) })).filter((g) => g.items.length)
}

export const slugify = (title) =>
  String(title || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)

export const CATEGORIES = ['AI & Machine Learning', 'Cybersecurity', 'Software Engineering']

export const projectDefaults = () => ({
  title: '', slug: '', category: CATEGORIES[0], subtitle: '', description: '', body_html: '',
  hero_image_url: '', thumbnail: '', stack_csv: '', actions: []
})

export function countByType(pages) {
  const out = {}
  for (const p of pages || []) out[p.type] = (out[p.type] || 0) + 1
  return out
}

// A crawled button look versus the canonical set (Templates tab): Discover, View on GitHub, Download.
const CANON_TEXT = /^(discover|view on github|download\b.*)$/i
export function buttonVerdict(variant) {
  const texts = variant?.texts || []
  const isBtn = /\bbtn\b/.test(variant?.classes || '')
  const ok = isBtn && texts.length > 0 && texts.every((t) => CANON_TEXT.test(String(t).trim()))
  return ok ? { ok: true, label: 'canonical' } : { ok: false, label: isBtn ? 'off-canon text' : 'off-canon style' }
}
