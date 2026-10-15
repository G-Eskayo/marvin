import { readSaved, writeSaved } from './saved_state.js'

export function pageOf(rows, page, size = 5) {
  const pages = Math.max(1, Math.ceil((rows || []).length / size))
  const p = Math.min(Math.max(0, page | 0), pages - 1)
  return { page: p, pages, rows: (rows || []).slice(p * size, p * size + size) }
}

export function sortRows(rows, key, boards) {
  if (!rows || rows.length === 0) return rows || []
  const copy = [...rows]

  if (key === 'priority') {
    copy.sort((a, b) => {
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      return aPri - bPri
    })
  } else if (key === 'oldest') {
    copy.sort((a, b) => (b.ageDays || 0) - (a.ageDays || 0))
  } else if (key === 'project') {
    copy.sort((a, b) => {
      const aName = projectNameFor(a, boards)
      const bName = projectNameFor(b, boards)
      return aName.localeCompare(bName)
    })
  }
  // 'unblocks' is identity — just return

  return copy
}

const SORT_KEY = 'needsYou.sort'

export function readSort(storage) {
  try {
    const v = storage?.getItem(SORT_KEY)
    if (!v) return 'unblocks'
    const data = JSON.parse(v)
    const value = data && typeof data === 'object' && data.value ? data.value : v
    return ['unblocks', 'priority', 'oldest', 'project'].includes(value) ? value : 'unblocks'
  } catch {
    return 'unblocks'
  }
}

export function writeSort(storage, sort) {
  try {
    storage?.setItem(SORT_KEY, JSON.stringify({ at: Date.now(), value: sort }))
  } catch {
    // quota or private window: choice isn't remembered
  }
}

const PRIORITY_PILL = {
  p0: 'bg-red-950 text-red-300',
  p1: 'bg-orange-950 text-orange-300',
  p2: 'bg-neutral-800 text-neutral-400',
  p3: 'bg-neutral-800 text-neutral-400'
}

export function pillFor(priority) {
  if (!priority || typeof priority !== 'string') return null
  return PRIORITY_PILL[priority] || null
}

export function kindLabel(kind) {
  if (kind === 'needs-info') return 'needs answer'
  if (kind === 'ready-for-human') return 'needs you'
  return 'waiting'
}

export function projectNameFor(row, boards) {
  if (!row || !row.projectId) return row?.repo?.split('/').pop() || 'unknown'
  const board = (boards || []).find((b) => b.repo === row.repo && (b.repo.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') === row.projectId || b.name?.toLowerCase() === row.projectId))
  if (board) return board.name
  // Fallback: derive from projectId (should be the slug)
  return row.projectId
}

export function mergeRefresh(prev, result) {
  if (!result) return prev || { rows: [], error: null }
  if (result.ok) {
    return { rows: result.rows || [], error: null }
  }
  // Failure: keep prior rows if any, attach error
  return { rows: prev?.rows || [], error: result.error || 'Unknown error' }
}
