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

export const ARCHIVE_AFTER_DAYS = 14
const DAY_MS = 86400_000

const TYPE_LABELS = new Set(['bug', 'enhancement', 'documentation', 'research-spike', 'breaking-change', 'question', 'duplicate', 'invalid', 'good first issue', 'help wanted'])
const STATE_LABELS = new Set(['ready-for-agent', 'ready-for-human', 'needs-triage', 'needs-info', 'needs-reengagement', 'wontfix'])

// What kind of tag a label is, so the board can colour and group them.
export function labelKind(name) {
  if (name.startsWith('claimed:')) return 'claim'
  if (/^(priority:|p[0-3]$)/.test(name)) return 'priority'
  if (STATE_LABELS.has(name)) return 'state'
  if (TYPE_LABELS.has(name)) return 'type'
  return 'other'
}

const REVIEW_STAGES = new Set(['verifying', 'gate', 'merging'])
// A claim label is a statement, not evidence. With no live dispatch, no recent pipeline stage and no
// touch on the ticket for a day, it is a stale claim (found 2026-10-05: 14 of them showed as "in progress").
export const STALE_CLAIM_MS = 24 * 3600_000

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
function openDependencies(issue, openNumbers) {
  const body = issue.body || ''
  const refs = []
  for (const m of body.matchAll(/\bBlocked by\s+(?:[\w.-]+\/[\w.-]+)?#(\d+)/gi)) refs.push(Number(m[1]))
  const sec = body.match(/##\s*Blocked by\s*\n([\s\S]*?)(?=\n##\s|$)/i)
  if (sec) for (const m of sec[1].matchAll(/#(\d+)/g)) refs.push(Number(m[1]))
  return [...new Set(refs)].filter((n) => openNumbers.has(n))
}

// First match wins; order is the board's meaning. See CONTEXT.md for the rules.
export function deriveColumn(issue, { prs = [], events = [], isLive = false, openNumbers = new Set(), now = Date.now() } = {}) {
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
  const deps = openDependencies(issue, openNumbers)
  if (deps.length) return { ...base, column: 'blocked', reason: `Blocked by ${deps.map((d) => `#${d}`).join(', ')}, still open` }
  if (last && last.status === 'failed' && !isLive) {
    const why = last.detail ? `: ${last.detail}` : ''
    return { ...base, column: 'blocked', reason: `Pipeline failed at ${last.stage}${why}` }
  }

  const claim = labels.find((l) => l.startsWith('claimed:'))
  if (claim && !isLive) {
    const touched = Math.max(Date.parse(issue.updatedAt) || 0, Date.parse(last?.timestamp) || 0)
    if (touched && now - touched > STALE_CLAIM_MS) {
      const days = Math.floor((now - touched) / (24 * 3600_000))
      return { ...base, column: 'blocked', reason: `Claimed by ${claim.slice('claimed:'.length)} but no activity for ${days} day${days === 1 ? '' : 's'}` }
    }
  }
  if (claim || isLive) {
    return { ...base, column: 'progress', reason: claim ? `Claimed by ${claim.slice('claimed:'.length)}` : 'Running now' }
  }

  if (labels.includes('ready-for-agent')) return { ...base, column: 'ready', reason: 'Waiting for an agent', owner: 'agent' }
  if (labels.includes('ready-for-human')) return { ...base, column: 'ready', reason: 'Needs a human', owner: 'human' }

  if (labels.includes('needs-info')) return { ...base, column: 'backlog', reason: 'Waiting on more info' }
  if (labels.includes('needs-triage')) return { ...base, column: 'backlog', reason: 'Needs triage' }
  return { ...base, column: 'backlog', reason: 'Not yet triaged' }
}

export function buildBoard({ repo, issues, prs, eventsByNumber = {}, liveNumbers = new Set(), now = Date.now() }) {
  const openNumbers = new Set(issues.filter((i) => i.state === 'OPEN').map((i) => i.number))
  const columns = COLUMNS.map((c) => ({ ...c, cards: [] }))
  const byId = Object.fromEntries(columns.map((c) => [c.id, c]))
  byId.done.archive = []
  const archiveBefore = now - ARCHIVE_AFTER_DAYS * DAY_MS

  for (const issue of issues) {
    const events = eventsByNumber[issue.number] || []
    const d = deriveColumn(issue, { prs, events, isLive: liveNumbers.has(issue.number), openNumbers, now })
    const names = labelNames(issue)
    const created = Date.parse(issue.createdAt)
    const card = {
      number: issue.number,
      title: issue.title,
      url: issue.url,
      labels: names,
      tags: names.map((name) => ({ name, kind: labelKind(name) })),
      claimedBy: names.find((l) => l.startsWith('claimed:'))?.slice('claimed:'.length) || null,
      blockedBy: openDependencies(issue, openNumbers),
      createdAt: issue.createdAt,
      closedAt: issue.closedAt || null,
      ageDays: Number.isFinite(created) ? Math.floor((now - created) / DAY_MS) : null,
      reason: d.reason,
      owner: d.owner,
      prs: d.prs,
      hasTimeline: events.length > 0
    }
    // Closed long ago -> archive (never deleted, just out of the way). A closed ticket with no date stays visible.
    const closedMs = Date.parse(issue.closedAt)
    if (d.column === 'done' && Number.isFinite(closedMs) && closedMs < archiveBefore) byId.done.archive.push(card)
    else byId[d.column].cards.push(card)
  }
  // Open work: oldest first = the order the pipeline would pick them. Done / archive: newest first.
  const newestFirst = (a, b) => (b.closedAt || '').localeCompare(a.closedAt || '')
  for (const c of columns) c.cards.sort(c.id === 'done' ? newestFirst : (a, b) => a.createdAt.localeCompare(b.createdAt))
  byId.done.archive.sort(newestFirst)
  return { repo, columns }
}

// Compact numbers for the project card in Docs: how many cards per column, how many still open.
export function summarizeBoard(board) {
  const counts = Object.fromEntries(board.columns.map((c) => [c.id, c.cards.length]))
  const archived = board.columns.reduce((n, c) => n + (c.archive?.length || 0), 0)
  const total = Object.values(counts).reduce((a, b) => a + b, 0) + archived
  return { counts, archived, total, open: total - archived - (counts.done || 0) }
}
