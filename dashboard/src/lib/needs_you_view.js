// Utilities for the Needs You list: sorting, pagination, caching
// All functions are pure and storage-injectable (no direct window references except for storage)

const STORAGE_SORT_KEY = 'needs-you:sort'
const STORAGE_CACHE_KEY = 'needs-you:rows'

// Sort rows by field and direction
export function sortRows(rows, sortBy = 'priority', direction = 'asc') {
  const sorted = [...rows]
  sorted.sort((a, b) => {
    let aVal = a[sortBy]
    let bVal = b[sortBy]

    // Handle special sort keys
    if (sortBy === 'priority') {
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      aVal = isNaN(aPri) ? 99 : aPri
      bVal = isNaN(bPri) ? 99 : bPri
    } else if (sortBy === 'age') {
      aVal = a.ageDays || 0
      bVal = b.ageDays || 0
    } else if (sortBy === 'unblocks') {
      aVal = a.unblocks?.count || 0
      bVal = b.unblocks?.count || 0
    } else if (sortBy === 'project') {
      aVal = a.project || ''
      bVal = b.project || ''
    }

    if (aVal === bVal) return 0
    const cmp = aVal < bVal ? -1 : 1
    return direction === 'asc' ? cmp : -cmp
  })
  return sorted
}

// Paginate rows (return one page), clamping pageNum to valid range
export function paginate(rows, pageSize = 5, pageNum = 0) {
  const size = Math.max(1, Math.floor(pageSize) || 5)
  const num = Math.max(0, Math.floor(pageNum) || 0)
  const maxPage = Math.max(0, Math.ceil(rows.length / size) - 1)
  const clampedPageNum = Math.min(num, maxPage)
  const start = clampedPageNum * size
  const end = start + size
  return {
    items: rows.slice(start, end),
    total: rows.length,
    pageNum: clampedPageNum,
    pageSize: size,
    hasNext: end < rows.length,
    hasPrev: clampedPageNum > 0
  }
}

// Kind label for rendering (e.g., "needs answer" or "needs you")
export function kindLabel(kind) {
  if (kind === 'needs-info') return 'needs answer'
  if (kind === 'ready-for-human') return 'needs you'
  return kind || ''
}

// Priority pill for rendering (always returns {label, colorClass}, grey for unknown)
export function priorityPill(priority) {
  if (!priority) return { label: 'P?', colorClass: 'bg-neutral-950/50 text-neutral-300' }
  const num = parseInt(priority[1])
  if (num === 0) return { label: 'P0', colorClass: 'bg-red-950/50 text-red-300' }
  if (num === 1) return { label: 'P1', colorClass: 'bg-orange-950/50 text-orange-300' }
  if (num === 2) return { label: 'P2', colorClass: 'bg-neutral-950/50 text-neutral-300' }
  if (num === 3) return { label: 'P3', colorClass: 'bg-neutral-950/50 text-neutral-300' }
  return { label: priority.toUpperCase(), colorClass: 'bg-neutral-950/50 text-neutral-300' }
}

// Load sort preference from storage
export function loadSort(storage = null) {
  if (!storage) return { field: 'unblocks', direction: 'desc' }
  try {
    const data = storage.getItem?.(STORAGE_SORT_KEY)
    if (!data) return { field: 'unblocks', direction: 'desc' }
    const parsed = JSON.parse(data)
    return { field: parsed.field || 'unblocks', direction: parsed.direction || 'desc' }
  } catch {
    return { field: 'unblocks', direction: 'desc' }
  }
}

// Save sort preference to storage
export function saveSort(field, direction, storage = null) {
  if (!storage) return
  try {
    storage.setItem?.(STORAGE_SORT_KEY, JSON.stringify({ field, direction }))
  } catch {
    // Silent fail on storage errors
  }
}

// Load cached rows from storage (returns {rows, at} or null)
export function loadCachedRows(storage = null) {
  if (!storage) return null
  try {
    const data = storage.getItem?.(STORAGE_CACHE_KEY)
    if (!data) return null
    const parsed = JSON.parse(data)
    if (parsed && Array.isArray(parsed.rows) && typeof parsed.at === 'number') {
      return { rows: parsed.rows, at: parsed.at }
    }
    return null
  } catch {
    return null
  }
}

// Save rows to storage cache (stores {rows, at})
export function saveCachedRows(rows, storage = null) {
  if (!storage) return
  try {
    storage.setItem?.(STORAGE_CACHE_KEY, JSON.stringify({ rows: Array.isArray(rows) ? rows : [], at: Date.now() }))
  } catch {
    // Silent fail on storage errors
  }
}
