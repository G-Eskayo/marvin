// Pure helpers for the "What's waiting on you" view: sorting, pagination, caching, rendering.
import { projectIdOf } from './projects.js'
import { agoText } from './usage_view.js'

export const SORTS = ['unblocks', 'priority', 'oldest', 'project']

// Sort rows by one of the defined sort keys
export function sortRows(rows, sortKey = 'unblocks', boards = []) {
  const sorted = [...rows]
  if (!SORTS.includes(sortKey)) sortKey = 'unblocks'

  if (sortKey === 'unblocks') {
    sorted.sort((a, b) => {
      if (a.unblocks.count !== b.unblocks.count) return b.unblocks.count - a.unblocks.count
      return rows.indexOf(a) - rows.indexOf(b) // stable
    })
  } else if (sortKey === 'priority') {
    sorted.sort((a, b) => {
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      if (aPri !== bPri) return aPri - bPri
      return rows.indexOf(a) - rows.indexOf(b)
    })
  } else if (sortKey === 'oldest') {
    sorted.sort((a, b) => {
      if (b.ageDays !== a.ageDays) return b.ageDays - a.ageDays
      return rows.indexOf(a) - rows.indexOf(b)
    })
  } else if (sortKey === 'project') {
    sorted.sort((a, b) => {
      const aProj = String(resolveProject(a, boards).name ?? resolveProject(a, boards).id ?? '').toLowerCase()
      const bProj = String(resolveProject(b, boards).name ?? resolveProject(b, boards).id ?? '').toLowerCase()
      if (aProj !== bProj) return aProj.localeCompare(bProj)
      return rows.indexOf(a) - rows.indexOf(b)
    })
  }

  return sorted
}

// Resolve a row's project to {id, name} by looking it up in boards
export function resolveProject(row, boards = []) {
  if (!boards || boards.length === 0) return { id: row.project, name: row.project }

  const board = boards.find((b) => {
    const projectId = projectIdOf(b.repo)
    return projectId === row.project
  })

  if (board) return { id: row.project, name: board.name }
  return { id: row.project, name: row.project }
}

// Paginate rows into pages of pageSize
export function paginate(rows, page = 1, pageSize = 5) {
  const totalPages = rows.length === 0 ? 1 : Math.ceil(rows.length / pageSize)
  page = Math.max(1, Math.min(page, totalPages))
  const start = (page - 1) * pageSize
  const pageRows = rows.slice(start, start + pageSize)
  return { page, totalPages, pageRows }
}

// Render a priority pill (p0 red, p1 orange, p2/p3/null grey)
export function pillStyle(priority) {
  if (priority === 'p0') {
    return { container: 'bg-red-950', text: 'text-red-300' }
  } else if (priority === 'p1') {
    return { container: 'bg-orange-950', text: 'text-orange-300' }
  }
  return { container: 'bg-neutral-800', text: 'text-neutral-400' }
}

// Label for ticket kind
export function kindLabel(kind) {
  if (kind === 'needs-info') return 'needs answer'
  if (kind === 'ready-for-human') return 'needs you'
  return 'action needed'
}

// Read cached rows from storage, with defensive deserialization
export function readCache(storage) {
  try {
    const stored = storage?.getItem?.('needsYouCache')
    if (!stored) return []
    const data = JSON.parse(stored)
    if (!Array.isArray(data)) return []
    return data
      .filter((r) => r && typeof r.number === 'number' && typeof r.repo === 'string' &&
        r.unblocks && typeof r.unblocks.count === 'number' && Array.isArray(r.unblocks.items))
      .map((r) => (/^p[0-3]$/.test(r.priority) ? r : { ...r, priority: null }))
  } catch {
    return []
  }
}

// Write rows to cache
export function writeCache(storage, rows) {
  try {
    storage?.setItem?.('needsYouCache', JSON.stringify(rows))
  } catch {
    // Silent fail on quota exceeded or private browsing
  }
}

// Read sort preference from storage, with validation
export function readSortPref(storage) {
  try {
    const pref = storage?.getItem?.('needsYouSort')
    if (pref && SORTS.includes(pref)) return pref
  } catch {
    // Silent fail
  }
  return 'unblocks'
}

// Write sort preference to storage
export function writeSortPref(storage, key) {
  try {
    if (SORTS.includes(key)) {
      storage?.setItem?.('needsYouSort', key)
    }
  } catch {
    // Silent fail
  }
}

// Guard against stale responses: only apply if reqId is the latest
export function shouldApply(reqId, latestReqId) {
  return reqId === latestReqId
}

// Initialize view state from cache and storage preferences
export function initialViewState(storage) {
  const cached = readCache(storage)
  return {
    rows: cached,
    sortKey: readSortPref(storage),
    lastUpdated: null,
    status: cached.length > 0 ? 'ok' : 'loading',
    error: null,
    page: 1,
    latestReqId: 0
  }
}

// Apply fetch error to state, preserving cached rows
export function applyFetchError(prevState, message) {
  return { ...prevState, status: 'error', error: message }
}

// Determine empty state message based on status
export function emptyStateText(status) {
  if (status === 'loading') return 'Loading…'
  if (status === 'error') return "Couldn't check what's waiting on you — try again shortly."
  return 'Nothing needs you right now.'
}

// Determine freshness text based on status, error, and last updated time
export function freshnessText({ status, error, lastUpdated, now = Date.now() }) {
  if (error) return lastUpdated ? `update failed — showing data from ${agoText(now - lastUpdated)}` : 'update failed'
  if (status === 'loading') return 'updating…'
  if (lastUpdated) return `updated ${agoText(now - lastUpdated)}`
  return 'loading…'
}
