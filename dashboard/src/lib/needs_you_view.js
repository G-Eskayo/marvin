// Pagination helper
export function paginate(rows, { page = 1, pageSize = 10 } = {}) {
  const totalPages = Math.ceil(rows.length / pageSize)
  const clampedPage = Math.max(1, Math.min(page, totalPages || 1))
  const start = (clampedPage - 1) * pageSize
  const end = start + pageSize
  const paginatedRows = rows.slice(start, end)

  return {
    rows: paginatedRows,
    currentPage: clampedPage,
    totalPages,
    pageSize,
    total: rows.length
  }
}

// Sort rows with multiple strategies
export function sortRows(rows, sortBy = 'unblocks') {
  const sorted = [...rows]

  if (sortBy === 'unblocks') {
    sorted.sort((a, b) => {
      if (a.unblocks.count !== b.unblocks.count) {
        return b.unblocks.count - a.unblocks.count
      }
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      if (aPri !== bPri) return aPri - bPri
      return b.ageDays - a.ageDays
    })
  } else if (sortBy === 'priority') {
    sorted.sort((a, b) => {
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      if (aPri !== bPri) return aPri - bPri
      return b.ageDays - a.ageDays
    })
  } else if (sortBy === 'age') {
    sorted.sort((a, b) => {
      if (a.ageDays !== b.ageDays) {
        return b.ageDays - a.ageDays
      }
      const aPri = a.priority ? parseInt(a.priority[1]) : 99
      const bPri = b.priority ? parseInt(b.priority[1]) : 99
      return aPri - bPri
    })
  } else if (sortBy === 'kind') {
    sorted.sort((a, b) => {
      const kindsOrder = { 'needs-info': 0, 'ready-for-human': 1 }
      const aOrder = kindsOrder[a.kind] ?? 99
      const bOrder = kindsOrder[b.kind] ?? 99
      if (aOrder !== bOrder) return aOrder - bOrder
      return b.unblocks.count - a.unblocks.count
    })
  }

  return sorted
}

// Save/load sort preference from localStorage
export function writeSort(sortBy) {
  if (['unblocks', 'priority', 'age', 'kind'].includes(sortBy)) {
    try {
      localStorage.setItem('needs-you-sort', sortBy)
    } catch {
      // localStorage may not be available
    }
  }
}

export function readSort() {
  try {
    const saved = localStorage.getItem('needs-you-sort')
    if (saved && ['unblocks', 'priority', 'age', 'kind'].includes(saved)) {
      return saved
    }
  } catch {
    // localStorage may not be available
  }
  return 'unblocks'
}

// Resolve project name for a projectId
export function resolveProjectFor(projectId, projects = []) {
  const found = projects.find((p) => p.id === projectId)
  if (found) return found
  return { id: projectId }
}

// Format priority as a pill with class
export function priorityPill(priority) {
  if (!priority) {
    return { label: 'none', class: 'bg-neutral-800 text-neutral-400' }
  }
  const level = parseInt(priority[1])
  if (level === 0) return { label: priority, class: 'bg-red-950 text-red-300' }
  if (level === 1) return { label: priority, class: 'bg-orange-950 text-orange-300' }
  if (level === 2) return { label: priority, class: 'bg-yellow-950 text-yellow-300' }
  return { label: priority, class: 'bg-neutral-800 text-neutral-400' }
}

// Format kind label with appropriate styling
export function kindLabel(kind) {
  if (kind === 'ready-for-human') {
    return { label: 'Ready for human', class: 'bg-blue-950 text-blue-300' }
  }
  if (kind === 'needs-info') {
    return { label: 'Needs info', class: 'bg-amber-950 text-amber-300' }
  }
  return { label: kind || 'Unknown', class: 'bg-neutral-800 text-neutral-400' }
}

