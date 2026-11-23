// MR Review's Merged view (marvin#419): rows grouped by day (Today, Yesterday, then dates), 5 days per page.
export const DAYS_PER_PAGE = 5

function dayKey(d) {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

export function groupByDay(rows, now = new Date()) {
  const today = dayKey(now)
  const y = new Date(now)
  y.setDate(y.getDate() - 1)
  const yesterday = dayKey(y)
  const days = []
  const index = new Map()
  for (const r of rows || []) {
    const d = new Date(r.at)
    const valid = !Number.isNaN(d.getTime())
    const key = valid ? dayKey(d) : 'unknown'
    if (!index.has(key)) {
      const label = !valid ? 'Unknown date' : key === today ? 'Today' : key === yesterday ? 'Yesterday' : d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
      index.set(key, { key, label, rows: [], sort: valid ? d.getTime() : -Infinity })
      days.push(index.get(key))
    }
    index.get(key).rows.push(r)
  }
  return days.sort((a, b) => b.sort - a.sort)
}

export function pageOf(days, page, size = DAYS_PER_PAGE) {
  const pages = Math.max(1, Math.ceil((days || []).length / size))
  const p = Math.min(Math.max(0, page | 0), pages - 1)
  return { page: p, pages, days: (days || []).slice(p * size, p * size + size) }
}

export function openDuration(createdAt, now = Date.now()) {
  if (!createdAt) return ''
  const ms = now - Date.parse(createdAt)
  if (ms < 0) return ''
  const days = Math.floor(ms / 86_400_000)
  if (days > 0) return `open ${days}d`
  const hours = Math.floor(ms / 3_600_000)
  if (hours > 0) return `open ${hours}h`
  const mins = Math.floor(ms / 60_000)
  return `open ${mins}m`
}

export function notesLine(notes = [], max = 3) {
  if (!notes?.length) return ''
  const shown = notes.slice(0, max)
  const text = shown.map((n) => n.reason).join(' → ')
  const more = notes.length > max ? ` (+${notes.length - max} more)` : ''
  return text + more
}

export function filterRows(rows = [], filter = 'All') {
  if (filter === 'All') return rows
  if (filter === 'Merged') return rows.filter((r) => r.kind === 'merged')
  if (filter === 'Still open') return rows.filter((r) => r.kind === 'open')
  if (filter === 'Dropped') return rows.filter((r) => r.kind === 'dropped')
  return rows
}
