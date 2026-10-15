// Pagination helper
export function paginate(rows, page, pageSize = 5) {
  const totalPages = Math.ceil(rows.length / pageSize)
  const clampedPage = Math.max(0, Math.min(page, totalPages - 1))
  const start = clampedPage * pageSize
  const end = start + pageSize
  return {
    rows: rows.slice(start, end),
    page: clampedPage,
    totalPages: totalPages || 1
  }
}

// Sort rows by the given key: 'unblocks' | 'priority' | 'oldest' | 'project'
export function sortRows(rows, sortKey = 'unblocks', boardsByRepo = {}) {
  const sorted = [...rows]
  const sort = (a, b) => {
    switch (sortKey) {
      case 'unblocks':
        return b.unblocks.count - a.unblocks.count
      case 'priority':
        {
          const aPri = a.priority ? parseInt(a.priority[1]) : 99
          const bPri = b.priority ? parseInt(b.priority[1]) : 99
          return aPri - bPri
        }
      case 'oldest':
        return b.ageDays - a.ageDays
      case 'project':
        {
          const aName = projectName(a, boardsByRepo)
          const bName = projectName(b, boardsByRepo)
          return aName.localeCompare(bName)
        }
      default:
        return 0
    }
  }
  sorted.sort(sort)
  return sorted
}

// Pill (badge) styling based on priority
export function pillFor(row) {
  let tone = 'grey'
  let text = row.kind === 'needs-info' ? 'needs answer' : 'needs you'
  if (row.priority === 'p0') {
    tone = 'red'
    text = `${text} (P0)`
  } else if (row.priority === 'p1') {
    tone = 'orange'
    text = `${text} (P1)`
  }
  return { text, tone }
}

// Get the board name for a row's project repo, falling back to short name
export function projectName(row, boardsByRepo = {}) {
  const repo = row.project.repo || row.repo
  const board = boardsByRepo[repo]
  return board?.name || repo.split('/')[1] || repo
}

// Merge fetch result into previous state: success replaces, failure keeps old rows + records error
// When seq and latestSeq are provided, drop stale (seq < latestSeq) results entirely
export function mergeNeedsYouResult(prev, result, { now = Date.now(), seq, latestSeq } = {}) {
  if (seq != null && latestSeq != null && seq < latestSeq) {
    return prev || { rows: [], timestamp: null, error: null }
  }
  if (result.error) {
    return {
      rows: prev?.rows || [],
      timestamp: prev?.timestamp || null,
      error: result.error
    }
  }
  return {
    rows: result.rows || [],
    timestamp: now,
    error: null
  }
}

// Read sort choice from storage with fallback
export function readSortChoice(storage) {
  try {
    const saved = storage?.getItem('needs-you.sort') ?? 'unblocks'
    const valid = ['unblocks', 'priority', 'oldest', 'project']
    return valid.includes(saved) ? saved : 'unblocks'
  } catch {
    return 'unblocks'
  }
}

// Write sort choice to storage
export function writeSortChoice(storage, sort) {
  try {
    storage?.setItem('needs-you.sort', sort)
  } catch {
    // quota or a private window: next launch just starts with default
  }
}
