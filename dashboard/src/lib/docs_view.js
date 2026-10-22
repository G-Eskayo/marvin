// The Docs tab's drill-down (#570, design docs/plans/docs-files-merge.md §0): Project (sidebar) → Kind (ONE chip row:
// Docs / Decisions / Deliverables) → Folder or file (tree) → Content (main pane). One control per level: the chip row
// is the only thing that chooses a kind, while browsing and while searching. Pure functions, so the rules are tested.

export const KINDS = ['docs', 'decisions', 'deliverables']
export const KIND_LABEL = { docs: 'Docs', decisions: 'Decisions', deliverables: 'Deliverables' }
const ADR = 'docs/adr/'

const flat = (tree) => (tree || []).flatMap((e) => (e.section ? e.items : [e]))

// The tree's three groups. Decisions = docs/adr/; Docs = everything else the tree lists (card, CONTEXT, README, other
// docs/ folders, notebooks); Deliverables = the outbox items matched to the project.
export function groupTree(tree, deliverables = []) {
  const top = []
  const sections = []
  let decisions = []
  for (const e of tree || []) {
    if (e.section === ADR) decisions = e.items
    else if (e.section) sections.push(e)
    else top.push(e)
  }
  const docsCount = top.length + sections.reduce((n, s) => n + s.items.length, 0)
  return {
    docs: { top, sections, count: docsCount },
    decisions: { items: decisions, count: decisions.length },
    deliverables: { items: deliverables || [], count: (deliverables || []).length }
  }
}

// No chip active = every group shows; otherwise only the chosen ones.
export const visibleKinds = (chips) => (chips && chips.size ? KINDS.filter((k) => chips.has(k)) : [...KINDS])

export function toggleChip(chips, kind) {
  const next = new Set(chips)
  if (next.has(kind)) next.delete(kind)
  else next.add(kind)
  return next
}

// The folder-card grid shows when only the Deliverables chip is active (whole project), or a deliverable folder is
// selected (that folder). Anything else selected in the tree wins over the chip.
export function mainView({ chips, selection, searching }) {
  if (searching) return 'search'
  if (selection?.type === 'folder') return 'folder'
  if (selection?.type === 'deliverable') return 'file'
  if (selection?.type === 'doc' && selection.path !== 'PROJECT.md') return 'doc'
  if (chips && chips.size === 1 && chips.has('deliverables')) return 'grid'
  return 'overview'
}

export function resultKind(r) {
  if (r?.kind === 'deliverable') return 'deliverables'
  return String(r?.path || '').startsWith(ADR) ? 'decisions' : 'docs'
}

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
const NOUN = { docs: ['Doc', 'Docs'], decisions: ['Decision', 'Decisions'], deliverables: ['Deliverable', 'Deliverables'] }

// Search results grouped Docs / Decisions / Deliverables; groups the chips don't allow are hidden and counted.
export function searchGroups(results, chips) {
  const show = new Set(visibleKinds(chips))
  const by = { docs: [], decisions: [], deliverables: [] }
  for (const r of results || []) by[resultKind(r)].push(r)
  const groups = KINDS.filter((k) => show.has(k) && by[k].length).map((k) => ({ kind: k, results: by[k] }))
  const hidden = Object.fromEntries(KINDS.filter((k) => !show.has(k) && by[k].length).map((k) => [k, by[k].length]))
  const shown = groups.reduce((n, g) => n + g.results.length, 0)
  return { groups, hidden, shown, total: (results || []).length }
}

// "2 Docs and 1 Decision hidden"
export function hiddenNote(hidden) {
  const parts = KINDS.filter((k) => hidden?.[k]).map((k) => `${hidden[k]} ${hidden[k] === 1 ? NOUN[k][0] : NOUN[k][1]}`)
  if (!parts.length) return ''
  return `${parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts.at(-1)}` : parts[0]} hidden`
}

// The count line over the results (mock-up ticket-403-f-4).
export function countLine({ query, docCount = 0, deliverableCount = 0, chips, grouped }) {
  const across = `across ${plural(docCount, 'doc')} and ${plural(deliverableCount, 'deliverable')}`
  const results = `${grouped.total === 1 ? 'result' : 'results'} for “${query}” ${across}`
  if (!chips || !chips.size) return `${grouped.total} ${results}`
  const showing = visibleKinds(chips).map((k) => KIND_LABEL[k]).join(' and ')
  const note = hiddenNote(grouped.hidden)
  return `${grouped.shown} of ${grouped.total} ${results} · showing ${showing} (the chip row filters results too)${note ? ` · ${note}` : ''}`
}

// The overview's summary rows: the first few docs (not the card) and the latest three decisions.
export function overviewPicks(groups) {
  const docs = [...groups.docs.top.filter((e) => e.path !== 'PROJECT.md'), ...groups.docs.sections.flatMap((s) => s.items)].slice(0, 4)
  const decisions = [...groups.decisions.items].sort((a, b) => b.path.localeCompare(a.path)).slice(0, 3)
  return { docs, decisions, deliverables: groups.deliverables.items.slice(0, 3) }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
// "2026-10-21" -> "21 Oct 2026"
export function formatDay(iso) {
  const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m || Number(m[2]) < 1 || Number(m[2]) > 12) return ''
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`
}

// "matched by phrase 'seal speak' in its docs" / "not matched: no project name, ticket, docs phrase or repo in its files"
export function matchedBy(entry) {
  return entry?.reason ? `matched by ${entry.reason}` : 'not matched: no project name, ticket, docs phrase or repo in its files'
}

// A deliverable row's second column on the overview (mock-up ticket-403-f-5a): "Folder · 1 file" or "Code · from ~/.claude/outbox".
export function deliverableSummary(entry) {
  if (entry?.isDir) return `Folder · ${plural(entry.count || 0, 'file')}`
  return `${(entry?.kinds || [])[0] || 'File'} · from ~/.claude/outbox`
}

export const docPaths = (tree) => flat(tree).map((e) => e.path)
