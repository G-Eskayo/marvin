// Pure functions for sorting and paginating the needsYou view.

const VALID_SORTS = new Set(['unblocks', 'priority', 'oldest', 'project'])
const DEFAULT_SORT = 'unblocks'
const STORAGE_KEY = 'activity.needsYou.sort'

// Read the saved sort order from storage, defaulting to 'unblocks'
export function readSort(storage) {
  try {
    if (!storage) return DEFAULT_SORT
    const saved = storage.getItem(STORAGE_KEY)
    if (saved && VALID_SORTS.has(saved)) return saved
  } catch {
    // storage can throw if the app is running in certain contexts
  }
  return DEFAULT_SORT
}

// Write the sort order to storage
export function writeSort(storage, sort) {
  if (!VALID_SORTS.has(sort)) throw new Error(`Invalid sort: ${sort}`)
  try {
    if (!storage) return
    storage.setItem(STORAGE_KEY, sort)
  } catch {
    // storage can throw if full or unavailable; fail silently on write
  }
}

// Stably re-sort rows according to the sort order.
// The backend already sorts by unblocks/priority/age, so 'unblocks' is a pass-through.
export function sortRows(rows, sort = 'unblocks') {
  if (!VALID_SORTS.has(sort)) sort = DEFAULT_SORT

  if (sort === 'unblocks') return rows

  const sorted = [...rows]
  if (sort === 'priority') {
    sorted.sort((a, b) => {
      const aPri = a.priority && /^p[0-3]$/.test(a.priority) ? parseInt(a.priority[1]) : 99
      const bPri = b.priority && /^p[0-3]$/.test(b.priority) ? parseInt(b.priority[1]) : 99
      if (aPri !== bPri) return aPri - bPri
      return b.ageDays - a.ageDays // stable tiebreak: oldest first
    })
  } else if (sort === 'oldest') {
    sorted.sort((a, b) => b.ageDays - a.ageDays)
  } else if (sort === 'project') {
    sorted.sort((a, b) => {
      const aProj = a.projectRepo || a.repo
      const bProj = b.projectRepo || b.repo
      if (aProj !== bProj) return aProj.localeCompare(bProj)
      return b.unblocks.count - a.unblocks.count // stable tiebreak: higher unblocks first
    })
  }

  return sorted
}

// Paginate rows into a page, returning { pageRows, pageCount, page }.
// Clamps page to valid bounds [1, pageCount].
export function paginate(rows, page = 1, pageSize = 5) {
  const pageCount = Math.ceil(rows.length / pageSize) || 1
  const safePage = Math.max(1, Math.min(page, pageCount))
  const start = (safePage - 1) * pageSize
  const end = start + pageSize
  const pageRows = rows.slice(start, end)
  return { pageRows, pageCount, page: safePage }
}
