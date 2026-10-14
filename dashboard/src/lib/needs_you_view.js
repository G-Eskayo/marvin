// Pure functions for the NeedsYouList view: paginating, sorting, and rendering rows

// Create a priority pill style object { label, className } from a row.
// Takes the full row object to access row.priority and row.kind.
export function pillFor(row) {
  if (!row || !row.priority) return { label: '', className: '' }
  const p = parseInt(row.priority[1]) // p0, p1, p2, p3 -> 0, 1, 2, 3
  const classMap = {
    0: 'bg-red-900 text-white',
    1: 'bg-orange-900 text-white',
    2: 'bg-yellow-800 text-white',
    3: 'bg-gray-700 text-white'
  }
  return {
    label: row.priority.toUpperCase(),
    className: classMap[p] || 'bg-gray-700 text-white'
  }
}

// Sort rows according to specification. Safe fallback on unknown keys.
// Defaults: null = unblocks desc, priority asc, age desc.
// Valid keys: null, 'default', 'priority', 'age', 'unblocks'
export function sortRows(rows, sortSpec = null) {
  const sorted = [...rows]
  // Normalize: null and 'default' are the same
  const key = sortSpec === 'default' ? null : sortSpec

  if (!key) {
    // Default: unblocks desc, priority asc (0 first), age desc (oldest first)
    sorted.sort((a, b) => {
      if (a.unblocks.count !== b.unblocks.count) {
        return b.unblocks.count - a.unblocks.count
      }
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      if (aPri !== bPri) return aPri - bPri
      return b.ageDays - a.ageDays
    })
  } else if (key === 'priority') {
    sorted.sort((a, b) => {
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      return aPri - bPri
    })
  } else if (key === 'age') {
    sorted.sort((a, b) => b.ageDays - a.ageDays)
  } else if (key === 'unblocks') {
    sorted.sort((a, b) => b.unblocks.count - a.unblocks.count)
  } else {
    // Unknown key: fall back to default
    return sortRows(rows, null)
  }
  return sorted
}

// Paginate rows: returns { page: 0-indexed, items: subset, total, count }
// pageSize defaults to 5 and is clamped to at least 1.
export function paginate(rows, page = 0, pageSize = 5) {
  const size = Math.max(1, pageSize)
  const total = rows.length
  const start = page * size
  const items = rows.slice(start, start + size)
  return { page, items, total, count: items.length }
}

// Decide whether to apply cached rows: true if cache is recent AND has content.
// Recent = within 30 seconds.
export function shouldApplyCachedRows(cached) {
  if (!cached || !cached.rows || cached.rows.length === 0) return false
  if (typeof cached.at !== 'number') return false
  const ageMs = Date.now() - cached.at
  return ageMs < 30_000
}

// Describe a single row for rendering: extract what we need to show.
// Returns { title, number, repo, repoShort, ask, priority, pill, unblocks, kind }
export function describeNeedsYouRow(row) {
  const repoShort = (row.repo || '').split('/')[1] || ''
  return {
    title: row.title,
    number: row.number,
    repo: row.repo,
    repoShort,
    ask: row.ask,
    priority: row.priority,
    pill: pillFor(row),
    unblocks: row.unblocks,
    kind: row.kind
  }
}
