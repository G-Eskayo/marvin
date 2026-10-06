// A ticket handed to the owner must say exactly what to do. Its "## Your task" section has four bold fields; this reads them
// (the same rule as lib/ticket_policy.py human_task_gaps, which keeps new tickets honest) so the dashboard can show the task
// up front, or say plainly that the ticket does not explain itself.

export const HUMAN_TASK_FIELDS = ['What I need from you', 'Where', 'How', 'What to send back']

export function parseHumanTask(body) {
  const none = { found: false, fields: {}, missing: [...HUMAN_TASK_FIELDS] }
  const m = String(body || '').match(/^##\s*Your task\s*$([\s\S]*?)(?=^##\s|(?![\s\S]))/im)
  if (!m) return none
  const section = m[1]
  const names = HUMAN_TASK_FIELDS.map((f) => f.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  const fields = {}
  const missing = []
  for (const f of HUMAN_TASK_FIELDS) {
    const fm = section.match(new RegExp(`\\*\\*${f}:?\\*\\*:?([\\s\\S]*?)(?=\\*\\*(?:${names}):?\\*\\*|(?![\\s\\S]))`, 'i'))
    const text = fm ? fm[1].trim() : ''
    if (text) fields[f] = text
    else missing.push(f)
  }
  return { found: true, fields, missing }
}
