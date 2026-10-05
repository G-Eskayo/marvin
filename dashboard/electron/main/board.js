import { hasEvidenceSchema, parseTicketRef } from './mr_review.js'

// Jira-style project board (CONTEXT.md "Project boards"). A board is never
// stored: columns are derived live from the tracker's issues + PRs plus the
// pipeline's stage events, so it can't drift from the real tickets.
export const COLUMNS = [
  { id: 'backlog', label: 'Backlog' },
  { id: 'ready', label: 'Ready' },
  { id: 'blocked', label: 'Blocked' },
  { id: 'progress', label: 'In progress' },
  { id: 'review', label: 'In review / testing' },
  { id: 'done', label: 'Done' }
]

const REVIEW_STAGES = new Set(['verifying', 'gate', 'merging'])

const labelNames = (issue) => (issue.labels || []).map((l) => l.name)

function closingPrs(issue, prs) {
  return prs
    .filter((p) => p.state === 'OPEN' && parseTicketRef(p.body || '') === String(issue.number))
    .map((p) => ({
      number: p.number,
      title: p.title,
      url: p.url,
      isDraft: !!p.isDraft,
      hasDevEvidence: hasEvidenceSchema(p.body) && !/##\s*Dev Environment Evidence\s*\n+\s*N\/A/i.test(p.body)
    }))
}

// Dependencies come from either inline "Blocked by #n" or the to-issues
// template's "## Blocked by" section (bullets of #n refs, or "None ...").
function openDependency(issue, openNumbers) {
  const body = issue.body || ''
  const refs = []
  for (const m of body.matchAll(/\bBlocked by\s+(?:[\w.-]+\/[\w.-]+)?#(\d+)/gi)) refs.push(Number(m[1]))
  const sec = body.match(/##\s*Blocked by\s*\n([\s\S]*?)(?=\n##\s|$)/i)
  if (sec) for (const m of sec[1].matchAll(/#(\d+)/g)) refs.push(Number(m[1]))
  return refs.find((n) => openNumbers.has(n)) ?? null
}

// First match wins; order is the board's meaning. See CONTEXT.md for the rules.
export function deriveColumn(issue, { prs = [], events = [], isLive = false, openNumbers = new Set() } = {}) {
  const labels = labelNames(issue)
  const linked = closingPrs(issue, prs)
  const last = events.length ? events[events.length - 1] : null
  const base = { prs: linked, owner: null }

  if (issue.state === 'CLOSED') return { ...base, column: 'done', reason: 'Closed' }

  if (linked.length) {
    return { ...base, column: 'review', reason: `PR #${linked[0].number} open: ${linked[0].title}` }
  }
  if (last && REVIEW_STAGES.has(last.stage) && last.status !== 'failed') {
    return { ...base, column: 'review', reason: `Pipeline at ${last.stage}` }
  }

  if (labels.includes('blocked')) return { ...base, column: 'blocked', reason: 'Labelled blocked' }
  const dep = openDependency(issue, openNumbers)
  if (dep !== null) return { ...base, column: 'blocked', reason: `Blocked by #${dep}, still open` }
  if (last && last.status === 'failed' && !isLive) {
    const why = last.detail ? `: ${last.detail}` : ''
    return { ...base, column: 'blocked', reason: `Pipeline failed at ${last.stage}${why}` }
  }

  const claim = labels.find((l) => l.startsWith('claimed:'))
  if (claim || isLive) {
    return { ...base, column: 'progress', reason: claim ? `Claimed by ${claim.slice('claimed:'.length)}` : 'Running now' }
  }

  if (labels.includes('ready-for-agent')) return { ...base, column: 'ready', reason: 'Waiting for an agent', owner: 'agent' }
  if (labels.includes('ready-for-human')) return { ...base, column: 'ready', reason: 'Needs a human', owner: 'human' }

  if (labels.includes('needs-info')) return { ...base, column: 'backlog', reason: 'Waiting on more info' }
  if (labels.includes('needs-triage')) return { ...base, column: 'backlog', reason: 'Needs triage' }
  return { ...base, column: 'backlog', reason: 'Not yet triaged' }
}

export function buildBoard({ repo, issues, prs, eventsByNumber = {}, liveNumbers = new Set() }) {
  const openNumbers = new Set(issues.filter((i) => i.state === 'OPEN').map((i) => i.number))
  const columns = COLUMNS.map((c) => ({ ...c, cards: [] }))
  const byId = Object.fromEntries(columns.map((c) => [c.id, c]))

  for (const issue of issues) {
    const events = eventsByNumber[issue.number] || []
    const d = deriveColumn(issue, { prs, events, isLive: liveNumbers.has(issue.number), openNumbers })
    byId[d.column].cards.push({
      number: issue.number,
      title: issue.title,
      url: issue.url,
      labels: labelNames(issue),
      createdAt: issue.createdAt,
      reason: d.reason,
      owner: d.owner,
      prs: d.prs,
      hasTimeline: events.length > 0
    })
  }
  // Oldest first within a column = the order the pipeline would pick them.
  for (const c of columns) c.cards.sort((a, b) => a.createdAt.localeCompare(b.createdAt))
  return { repo, columns }
}

// Compact numbers for the project card in Docs: how many cards per column, how many still open.
export function summarizeBoard(board) {
  const counts = Object.fromEntries(board.columns.map((c) => [c.id, c.cards.length]))
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  return { counts, total, open: total - (counts.done || 0) }
}
