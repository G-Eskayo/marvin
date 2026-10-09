// Parse 'Revisit by: YYYY-MM-DD [— condition]' comments (mirrors lib/ticket_policy.py for consistency)
const REVISIT_LINE = /^\s*Revisit\s+by:\s*(\d{4}-\d{2}-\d{2})\s*(?:[-–—]\s*(.+))?$/im

export function parseRevisitComment(comment) {
  if (!comment || typeof comment !== 'object') return null
  const body = comment.body || ''
  if (!body) return null

  const m = body.match(REVISIT_LINE)
  if (!m) return null

  const dateStr = m[1]
  const condition = (m[2] || '').trim()

  // Validate date format
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return null
  const d = new Date(`${dateStr}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return null

  let ref = null
  if (condition) {
    const refMatch = condition.match(/#(\d+)/)
    if (refMatch) {
      ref = parseInt(refMatch[1], 10)
    }
  }

  return { date: dateStr, condition: condition || null, ref }
}

export function latestRevisit(comments) {
  if (!Array.isArray(comments)) return null

  const candidates = []
  for (let i = 0; i < comments.length; i++) {
    const parsed = parseRevisitComment(comments[i])
    if (parsed) {
      const createdAt = comments[i].createdAt
      if (createdAt) {
        const ts = new Date(createdAt).getTime()
        if (!Number.isNaN(ts)) {
          candidates.push({ ts, i, parsed })
        }
      }
    }
  }

  if (!candidates.length) return null

  // Sort by timestamp descending, then by index descending (last one wins on tie)
  candidates.sort((a, b) => (b.ts - a.ts) || (b.i - a.i))
  return candidates[0].parsed
}
