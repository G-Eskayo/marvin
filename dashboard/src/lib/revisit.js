// Parse revisit comments: "Revisit by: YYYY-MM-DD [— condition]" or "Revisit by: YYYY-MM-DD [- condition]"
// Mirrors lib/ticket_policy.py's parse_revisit_comment/latest_revisit.

export function parseRevisitComment(comment) {
  if (!comment || typeof comment.body !== 'string') return null
  const body = comment.body
  const match = body.match(/Revisit by:\s*(\d{4}-\d{2}-\d{2})\s*(?:[—-]\s*(.+))?/i)
  if (!match) return null
  const date = match[1]
  const condition = match[2]?.trim() || null
  const d = new Date(date + 'T00:00:00Z')
  if (isNaN(d.getTime())) return null
  return { date, condition }
}

function isValidDate(dateString) {
  if (!dateString) return false
  const d = new Date(dateString)
  return !isNaN(d.getTime())
}

export function latestRevisit(comments) {
  if (!Array.isArray(comments)) return null
  let best = null
  for (const comment of comments) {
    const parsed = parseRevisitComment(comment)
    if (!parsed) continue
    const commentDate = comment.createdAt || ''
    const isCommentDateValid = isValidDate(commentDate)
    if (!best) {
      best = { ...parsed, createdAt: commentDate, isValid: isCommentDateValid }
      continue
    }
    const isBestDateValid = best.isValid
    if (isCommentDateValid && !isBestDateValid) {
      best = { ...parsed, createdAt: commentDate, isValid: isCommentDateValid }
    } else if (isCommentDateValid === isBestDateValid && commentDate > best.createdAt) {
      best = { ...parsed, createdAt: commentDate, isValid: isCommentDateValid }
    }
  }
  if (!best) return null
  const { createdAt, isValid, ...result } = best
  return result
}
