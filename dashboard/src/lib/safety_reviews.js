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

// The card's excerpt: the entry's first part as markdown, cut cleanly. Cuts only at line ends, preferring the last
// paragraph break within `budget` characters; never inside a code fence (a fence still open at the cut is closed).
// A table or list cut at a line end is still a table or list. One huge line is kept whole; the card clips it.
const FENCE = /^\s{0,3}(```|~~~)/
export function excerptMarkdown(body, budget = 400) {
  if (typeof body !== 'string' || !body) return { text: '', cut: false }
  const lines = body.split('\n')
  let inFence = false
  let fenceMark = '```'
  let used = 0
  let lastBreak = -1 // index of the last blank line outside a fence
  let end = lines.length
  for (let i = 0; i < lines.length; i++) {
    const m = FENCE.exec(lines[i])
    if (m) {
      if (!inFence) fenceMark = m[1]
      inFence = !inFence
    }
    if (!inFence && !lines[i].trim()) lastBreak = i
    used += lines[i].length + 1
    if (used >= budget) {
      end = !inFence && lastBreak > 0 ? lastBreak : i + 1
      break
    }
  }
  if (end >= lines.length) return { text: body, cut: false }
  const kept = lines.slice(0, end)
  // No trailing blank lines, and no heading left with nothing under it.
  const dangling = () => kept.length > 1 && (!kept[kept.length - 1].trim() || /^\s{0,3}#{1,6}\s/.test(kept[kept.length - 1]))
  while (dangling()) kept.pop()
  // Re-scan what is kept: a fence open at the cut is closed so the rest never renders as code.
  let open = false
  let mark = '```'
  for (const l of kept) {
    const m = FENCE.exec(l)
    if (m) { if (!open) mark = m[1]; open = !open }
  }
  if (open) kept.push(mark)
  return { text: kept.join('\n'), cut: true }
}
