// Display rules for Health ▸ Safety reviews (approved 2026-10-26). Pure; shared by the card and the main process.

export const NOTE_CAP = 1000 // process_quarantine_reviews.py NOTE_CAP: one line of "what to change"

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// research_colony -> "Research colony"
export function sourceLabel(loop) {
  const s = String(loop ?? '').replace(/_/g, ' ').trim()
  return s ? s[0].toUpperCase() + s.slice(1) : 'Unknown source'
}

// 2026-10-24 -> "Oct 24" (read as written: no time zone can move it a day)
export function shortDate(date) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(date ?? ''))
  const month = m && MONTHS[Number(m[2]) - 1]
  return month ? `${month} ${Number(m[3])}` : String(date ?? '')
}

export const fixed2 = (n) => (typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : '—')

// The card on screen stays while it is still pending (a sync can add or remove others); otherwise the first one.
export function pickCurrent(entries, currentId) {
  const list = Array.isArray(entries) ? entries : []
  return list.find((e) => e.id === currentId) || list[0] || null
}

// "N of total": answers given this session count into the total, so the total holds as answered entries leave the file.
export function progressOf(answered, pending) {
  const total = answered + pending
  return { position: Math.min(answered + 1, Math.max(total, 1)), total, answered, left: pending }
}

export const validNote = (text) => typeof text === 'string' && !!text.trim() && text.length <= NOTE_CAP
