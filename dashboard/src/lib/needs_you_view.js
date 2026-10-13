// Storage-injectable utilities for the NeedsYou list view
// All functions accept optional storage parameter for testability; no direct window reference

const CACHE_KEY = 'marvin_needsyou_cache'
const SORT_KEY = 'marvin_needsyou_sort'

// Sort rows by the given key
export function sortRows(rows, key) {
  const sorted = [...rows]
  if (key === 'priority') {
    sorted.sort((a, b) => {
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      return aPri - bPri
    })
  } else if (key === 'unblocks') {
    sorted.sort((a, b) => b.unblocks.count - a.unblocks.count)
  } else if (key === 'age') {
    sorted.sort((a, b) => b.ageDays - a.ageDays)
  } else if (key === 'project') {
    sorted.sort((a, b) => (a.project || '').localeCompare(b.project || ''))
  }
  return sorted
}

// Paginate rows
export function paginate(rows, page, pageSize) {
  const totalPages = Math.ceil(rows.length / pageSize) || 1
  const clamped = Math.max(1, Math.min(page || 1, totalPages))
  const start = (clamped - 1) * pageSize
  const end = start + pageSize
  return {
    items: rows.slice(start, end),
    totalPages,
    currentPage: clamped,
    totalCount: rows.length
  }
}

// Get CSS class and text for priority badge
export function priorityPill(priority) {
  if (!priority) return null
  if (priority === 'p0') return { className: 'bg-red-950 text-red-300', text: 'Critical' }
  if (priority === 'p1') return { className: 'bg-orange-950 text-orange-300', text: 'High' }
  if (priority === 'p2') return { className: 'bg-yellow-950 text-yellow-300', text: 'Medium' }
  if (priority === 'p3') return { className: 'bg-neutral-800 text-neutral-300', text: 'Low' }
  return { className: 'bg-neutral-800 text-neutral-300', text: priority }
}

// Get display text for kind label
export function kindLabel(kind) {
  if (kind === 'needs-info') return 'Needs info'
  if (kind === 'ready-for-human') return 'Ready for you'
  return kind
}

// Read cached rows from storage
export function readCache(storage = typeof window !== 'undefined' ? window.localStorage : null) {
  if (!storage) return null
  try {
    const cached = storage.getItem(CACHE_KEY)
    if (!cached) return null
    const parsed = JSON.parse(cached)
    return Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}

// Write rows to cache
export function writeCache(storage, rows) {
  if (!storage) return
  try {
    storage.setItem(CACHE_KEY, JSON.stringify(rows))
  } catch {
    // Storage full or unavailable; silently fail
  }
}

// Read saved sort key from storage
export function readSort(storage = typeof window !== 'undefined' ? window.localStorage : null) {
  if (!storage) return 'default'
  try {
    return storage.getItem(SORT_KEY) || 'default'
  } catch {
    return 'default'
  }
}

// Write sort key to storage
export function writeSort(storage, key) {
  if (!storage) return
  try {
    storage.setItem(SORT_KEY, key)
  } catch {
    // Storage full or unavailable; silently fail
  }
}

// Reducer for fetching state transitions
export function applyFetch(state, action) {
  const { type, payload } = action
  if (type === 'FETCH_START') {
    return { ...state, loading: true, error: null, requestId: payload?.requestId }
  }
  if (type === 'FETCH_SUCCESS') {
    return { ...state, loading: false, error: null, rows: payload.rows, lastFetch: payload.at, requestId: payload?.requestId }
  }
  if (type === 'FETCH_ERROR') {
    return { ...state, loading: false, error: payload.error, requestId: payload?.requestId }
  }
  if (type === 'SET_SORT') {
    return { ...state, sortKey: payload.key, page: 1 }
  }
  if (type === 'SET_PAGE') {
    return { ...state, page: payload.page }
  }
  return state
}
