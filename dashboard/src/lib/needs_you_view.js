// Pure functions for the NeedsYouList view: pagination, sorting, preferences, and UI helpers
import { projectIdOf } from './projects.js'

export const PAGE_SIZE = 5
export const SORT_ORDERS = ['unblocks', 'priority', 'oldest', 'project']

// Apply pagination: split rows into pages of given size
export function paginate(rows, page = 1, pageSize = PAGE_SIZE) {
  const clampedSize = Math.max(1, Math.floor(pageSize ?? 1) || 1)
  const totalPages = Math.max(1, Math.ceil(rows.length / clampedSize))
  const clampedPage = Math.max(1, Math.min(Math.floor(page ?? 1) || 1, totalPages))
  const start = (clampedPage - 1) * clampedSize
  const end = start + clampedSize
  const items = rows.slice(start, end)
  return { items, page: clampedPage, totalPages, total: rows.length }
}

// Sort rows by the chosen order
export function sortRows(rows, order = 'unblocks', boards = []) {
  const sorted = [...rows]
  if (order === 'unblocks') {
    // Passthrough: maintain backend order (unblocks desc, then priority, then age)
    return sorted
  } else if (order === 'priority') {
    sorted.sort((a, b) => {
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      if (aPri !== bPri) return aPri - bPri
      const aAge = Number.isFinite(a.ageDays) ? a.ageDays : 0
      const bAge = Number.isFinite(b.ageDays) ? b.ageDays : 0
      return bAge - aAge
    })
  } else if (order === 'oldest') {
    sorted.sort((a, b) => {
      const aAge = Number.isFinite(a.ageDays) ? a.ageDays : 0
      const bAge = Number.isFinite(b.ageDays) ? b.ageDays : 0
      return bAge - aAge
    })
  } else if (order === 'project') {
    sorted.sort((a, b) => {
      const aProjName = resolveProjectName(a, boards)
      const bProjName = resolveProjectName(b, boards)
      return (aProjName || '').localeCompare(bProjName || '')
    })
  }
  return sorted
}

// Build the priority pill: visual label for priority level
export function priorityPill(priority, kind) {
  if (!priority) return null
  const level = parseInt(priority[1])
  const colors = {
    0: 'bg-red-900 text-red-300',
    1: 'bg-orange-900 text-orange-300',
    2: 'bg-yellow-900 text-yellow-300',
    3: 'bg-neutral-700 text-neutral-300'
  }
  const label = `P${level}`
  return { level, label, className: colors[level] || 'bg-neutral-700 text-neutral-300' }
}

// Resolve the display name of a project from a row and boards list
export function resolveProjectName(row, boards = []) {
  if (!row) return null
  const projId = row.projectId || projectIdOf(row.repo)
  if (!projId) return null
  const board = boards.find((b) => projectIdOf(b.repo) === projId)
  return board?.name || projId
}

const SORT_PREF_KEY = 'needsyou.sort'

// Read the user's sort preference from storage (defaults to 'unblocks')
export function readSortPref(storage) {
  try {
    const saved = JSON.parse(storage?.getItem(SORT_PREF_KEY) ?? '"unblocks"')
    return SORT_ORDERS.includes(saved) ? saved : 'unblocks'
  } catch {
    return 'unblocks'
  }
}

// Write the user's sort preference to storage
export function writeSortPref(storage, order) {
  try {
    storage?.setItem(SORT_PREF_KEY, JSON.stringify(order))
  } catch {
    // quota or private window: preference is lost
  }
}
