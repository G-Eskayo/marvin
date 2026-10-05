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
// The theme scopes much of its typography and image treatment (the Roboto Slab titles, the grayscale photos) to where an
// element sits on a real page, so a preview wraps the element in the same ancestors the live site has:
//   'chrome' -- header / title bar / footer: they sit OUTSIDE <main>, so only the page wrapper
//   'page'   -- anything authored inside a page: the wrapper, <main>, the content column
//   'grid'   -- a project card: the page context plus the card grid (.other > .container > .row > .col-md-12.sm-2-items > .row)
//   'section'-- a category section (heading + card grid): the page context plus the .other > .container > .row it sits in
export function previewDocument(html, head, { wide = false, width = null, context = 'page' } = {}) {
  // Page templates are WordPress/Avada shortcodes that the server expands; in a preview only the real markup
  // inside them should show, not the tokens.
  html = String(html || '').replace(/\[\/?fusion_[a-z_]+[^\]]*\]/g, '')
  if (context === 'grid') {
    html = `<div class="other"><div class="container"><div class="row"><div class="col-md-12 sm-2-items"><div class="row">${html}</div></div></div></div></div>`
  }
  if (context === 'section') {
    html = `<div class="other"><div class="container"><div class="row">${html}</div></div></div>`
  }
  if (context !== 'chrome') {
    html = `<main id="main" class="clearfix"><div class="fusion-row"><section id="content"><div class="post-content">${html}</div></section></div></main>`
  }
  // The site's own <body> class (carried in the head by the main process) so theme rules scoped to it apply.
  const bodyClass = ((head || '').match(/<meta name="preview-body-class" content="([^"]*)">/) || [])[1] || ''
  const max = width ? `${Number(width)}px` : wide ? 'none' : '340px'
  return `<!doctype html><html><head><meta charset="utf-8">${head || ''}<style>html,body,#wrapper,#boxed-wrapper,#main{height:auto!important;min-height:0!important}</style></head><body class="${bodyClass}" style="margin:0;padding:16px;background:#fff"><div id="boxed-wrapper"><div id="wrapper" class="fusion-wrapper" style="max-width:${max}">${html}</div></div></body></html>`
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

// How stale the crawled inventory may get before the tab quietly re-crawls it on open.
export const INVENTORY_MAX_AGE_MS = 10 * 60 * 1000
export function inventoryIsStale(generatedAt, now = Date.now(), maxAge = INVENTORY_MAX_AGE_MS) {
  const t = Date.parse(generatedAt || '')
  return Number.isNaN(t) || now - t > maxAge
}
