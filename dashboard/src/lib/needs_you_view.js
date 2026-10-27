import { readSaved, writeSaved } from './saved_state.js'

const SAVED_SORT_KEY = 'needs_you.sort'
const KNOWN_SORT_IDS = ['unblocks', 'priority', 'oldest', 'project']
const MAX_ROWS = 10000

export function bodyState(rows, error) {
  if (error) return 'error'
  if (rows.length === 0) return 'empty'
  return 'loaded'
}

export function sanitizeRows(value) {
  if (!Array.isArray(value)) return []
  if (value.length > MAX_ROWS) return value.slice(0, MAX_ROWS)
  return value.filter(row => {
    if (!row || typeof row !== 'object') return false
    if (typeof row.number !== 'number') return false
    if (typeof row.title !== 'string') return false
    if (typeof row.repo !== 'string') return false
    if (!row.unblocks || typeof row.unblocks.count !== 'number') return false
    if (typeof row.kind !== 'string' || !row.kind) return false
    return true
  })
}

export function paginate(rows, page = 0, size = 5) {
  const start = page * size
  const end = start + size
  return {
    items: rows.slice(start, end),
    page,
    size,
    total: rows.length,
    pages: Math.ceil(rows.length / size)
  }
}

export function sortRows(rows, sortId, { boards = [] } = {}) {
  const sorted = [...rows]

  if (sortId === 'unblocks') {
    sorted.sort((a, b) => b.unblocks.count - a.unblocks.count)
  } else if (sortId === 'priority') {
    sorted.sort((a, b) => {
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      return aPri - bPri
    })
  } else if (sortId === 'oldest') {
    sorted.sort((a, b) => b.ageDays - a.ageDays)
  } else if (sortId === 'project') {
    sorted.sort((a, b) => {
      const aName = boards.find((board) => board.repo === a.repo)?.name || a.repo.split('/')[1]
      const bName = boards.find((board) => board.repo === b.repo)?.name || b.repo.split('/')[1]
      const nameCompare = aName.localeCompare(bName)
      return nameCompare !== 0 ? nameCompare : a.number - b.number
    })
  }

  return sorted
}

export function priorityStyle(priority, kind) {
  if (!priority) {
    return {
      bg: 'bg-neutral-900',
      text: 'text-neutral-400',
      label: kind === 'needs-info' ? 'needs answer' : 'needs you'
    }
  }

  const level = parseInt(priority[1])
  if (level === 0) {
    return {
      bg: 'bg-red-950',
      text: 'text-red-300',
      label: `P${level}`
    }
  } else if (level === 1) {
    return {
      bg: 'bg-orange-950',
      text: 'text-orange-300',
      label: `P${level}`
    }
  }
  return {
    bg: 'bg-neutral-900',
    text: 'text-neutral-400',
    label: `P${level}`
  }
}

export function readSortPreference(storage) {
  const saved = readSaved(storage, SAVED_SORT_KEY)
  const pref = saved?.value || 'unblocks'
  return KNOWN_SORT_IDS.includes(pref) ? pref : 'unblocks'
}

export function writeSortPreference(storage, sortId) {
  writeSaved(storage, SAVED_SORT_KEY, sortId)
}
