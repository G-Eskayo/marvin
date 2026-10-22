import { readSaved, writeSaved } from './saved_state.js'

const SORT_OPTIONS = [
  { id: 'unblocks', label: 'Unblocks (most first)' },
  { id: 'priority', label: 'Priority (high first)' },
  { id: 'age', label: 'Age (oldest first)' },
  { id: 'project', label: 'Project' }
]

export function getSortOptions() {
  return SORT_OPTIONS
}

export function sortRows(rows, sortBy = 'unblocks') {
  const sorted = [...rows]
  sorted.sort((a, b) => {
    switch (sortBy) {
      case 'unblocks': {
        const aCount = a.unblocks?.count ?? 0
        const bCount = b.unblocks?.count ?? 0
        if (aCount !== bCount) return bCount - aCount
        return b.ageDays - a.ageDays
      }
      case 'priority': {
        const aPri = a.priority ? (parseInt(a.priority[1]) || 99) : 99
        const bPri = b.priority ? (parseInt(b.priority[1]) || 99) : 99
        if (aPri !== bPri) return aPri - bPri
        return b.ageDays - a.ageDays
      }
      case 'age':
        return b.ageDays - a.ageDays
      case 'project': {
        const aProj = a.project ?? a.repo ?? ''
        const bProj = b.project ?? b.repo ?? ''
        if (aProj !== bProj) return aProj.localeCompare(bProj)
        const aCount = a.unblocks?.count ?? 0
        const bCount = b.unblocks?.count ?? 0
        return bCount - aCount
      }
      default:
        return 0
    }
  })
  return sorted
}

export function paginate(rows, pageNumber = 1, pageSize = 5) {
  const totalPages = Math.ceil(rows.length / pageSize)
  const clampedPage = Math.max(1, Math.min(pageNumber, totalPages || 1))
  const start = (clampedPage - 1) * pageSize
  const end = start + pageSize
  return {
    rows: rows.slice(start, end),
    currentPage: clampedPage,
    pageSize,
    totalRows: rows.length,
    totalPages
  }
}

export function priorityPill(priority) {
  if (!priority) return null
  const num = parseInt(priority[1])
  const colors = { 0: 'bg-red-900 text-red-300', 1: 'bg-orange-900 text-orange-300' }
  const className = colors[num] || 'bg-neutral-800 text-neutral-400'
  return { text: priority.toUpperCase(), className }
}

export function kindLabel(kind) {
  if (kind === 'needs-info') return 'needs answer'
  if (kind === 'ready-for-human') return 'needs you'
  return 'needs you'
}

export function applyLoadResult(saved, loaded) {
  if (Array.isArray(loaded)) return loaded
  return saved
}

// Saved state for sort preference
const SORT_KEY = 'needsYou.sort'

export function readSortPreference(storage) {
  try {
    const val = storage?.getItem(SORT_KEY)
    return (val && SORT_OPTIONS.some(o => o.id === val)) ? val : 'unblocks'
  } catch {
    return 'unblocks'
  }
}

export function writeSortPreference(storage, sortBy) {
  try {
    storage?.setItem(SORT_KEY, sortBy)
  } catch {
    // quota or private window
  }
}
