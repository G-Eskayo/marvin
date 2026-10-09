import { hasEvidenceSchema, parseTicketRef } from './mr_review.js'
import { latestRevisit } from '../../src/lib/revisit.js'

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
const STATE_LABELS = new Set(['hold', 'ready-for-agent', 'ready-for-human', 'needs-triage', 'needs-info', 'needs-reengagement', 'wontfix'])

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
function dependencyRefs(issue) {
  const body = issue.body || ''
  const refs = []
  for (const m of body.matchAll(/\bBlocked by\s+(?:[\w.-]+\/[\w.-]+)?#(\d+)/gi)) refs.push(Number(m[1]))
  const sec = body.match(/##\s*Blocked by\s*\n([\s\S]*?)(?=\n##\s|$)/i)
  if (sec) for (const m of sec[1].matchAll(/#(\d+)/g)) refs.push(Number(m[1]))
  return [...new Set(refs)]
}

// A ticket that is on hold, or was closed as not planned, will not be finished soon (or ever), so waiting on
// it would park the dependent forever. Those are not blockers; the dependent's card says it is ignoring them.
function openDependencies(issue, openNumbers, ignored = new Set()) {
  return dependencyRefs(issue).filter((n) => openNumbers.has(n) && !ignored.has(n))
}

const refList = (nums) => nums.map((n) => `#${n}`).join(', ')

// "- [x] done / - [ ] not yet" items in the acceptance criteria (or the whole body if it has no such
// section), so a half-finished ticket shows how far it got.
export function checklistProgress(body) {
  if (!body) return null
  const sec = body.match(/##\s*Acceptance criteria\s*\n([\s\S]*?)(?=\n##\s|$)/i)
  const items = [...(sec ? sec[1] : body).matchAll(/^\s*[-*]\s*\[([ xX])\]/gm)]
  if (!items.length) return null
  return { done: items.filter((m) => m[1] !== ' ').length, total: items.length }
}

// First match wins; order is the board's meaning. See CONTEXT.md for the rules.
export function deriveColumn(issue, ctx = {}) {
  const result = deriveColumnCore(issue, ctx)
  if (result.column === 'done') return result
  const { heldNumbers = new Set(), notPlannedNumbers = new Set() } = ctx
  const refs = dependencyRefs(issue)
  const held = refs.filter((n) => heldNumbers.has(n))
  const dropped = refs.filter((n) => notPlannedNumbers.has(n))
  const notes = []
  if (held.length) notes.push(`${refList(held)} ${held.length === 1 ? 'is' : 'are'} on hold, not blocking`)
  if (dropped.length) notes.push(`${refList(dropped)} ${dropped.length === 1 ? 'was' : 'were'} closed as not planned, not blocking`)
  return notes.length ? { ...result, reason: `${result.reason} (${notes.join('; ')})` } : result
}

function deriveColumnCore(issue, { prs = [], events = [], isLive = false, openNumbers = new Set(), heldNumbers = new Set(), notPlannedNumbers = new Set(), now = Date.now() } = {}) {
  const labels = labelNames(issue)
  const linked = closingPrs(issue, prs)
  const last = events.length ? events[events.length - 1] : null
  const base = { prs: linked, owner: null }

  if (issue.state === 'CLOSED') return { ...base, column: 'done', reason: 'Closed' }

  if (linked.length && labels.includes('needs-reengagement')) {
    // Denied in review (or failed the merge gate): the PR stays open, but the next move is the agent's, not
    // yours. MR Review shows the same PR as "sent back", so the two views say the same thing.
    return { ...base, column: 'blocked', reason: `Sent back from review: waiting for rework (PR #${linked[0].number} still open)` }
  }
  if (linked.length) {
    return { ...base, column: 'review', reason: `PR #${linked[0].number} open: ${linked[0].title}` }
  }
  if (last && REVIEW_STAGES.has(last.stage) && last.status !== 'failed') {
    return { ...base, column: 'review', reason: `Pipeline at ${last.stage}` }
  }

  if (labels.includes('hold')) return { ...base, column: 'backlog', reason: 'On hold', held: true }
  if (labels.includes('blocked')) return { ...base, column: 'blocked', reason: 'Labelled blocked' }
  const deps = openDependencies(issue, openNumbers, new Set([...heldNumbers, ...notPlannedNumbers]))
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

export function buildBoard({ repo, issues, prs, eventsByNumber = {}, liveNumbers = new Set(), evidenceByNumber = {}, holdComments = {}, now = Date.now() }) {
  const openNumbers = new Set(issues.filter((i) => i.state === 'OPEN').map((i) => i.number))
  const heldNumbers = new Set(issues.filter((i) => i.state === 'OPEN' && labelNames(i).includes('hold')).map((i) => i.number))
  const notPlannedNumbers = new Set(issues.filter((i) => i.state === 'CLOSED' && i.stateReason === 'NOT_PLANNED').map((i) => i.number))
  const ignored = new Set([...heldNumbers, ...notPlannedNumbers])
  const columns = COLUMNS.map((c) => ({ ...c, cards: [] }))
  const byId = Object.fromEntries(columns.map((c) => [c.id, c]))
  byId.done.archive = []
  const archiveBefore = now - ARCHIVE_AFTER_DAYS * DAY_MS

  for (const issue of issues) {
    const events = eventsByNumber[issue.number] || []
    const d = deriveColumn(issue, { prs, events, isLive: liveNumbers.has(issue.number), openNumbers, heldNumbers, notPlannedNumbers, now })
    const names = labelNames(issue)
    const created = Date.parse(issue.createdAt)
    // Git is what happened, labels are what was said: surface work that already exists (lib/ticket_evidence.py).
    const ev = evidenceByNumber[issue.number]
    const evidence = ev ? { verdict: ev.verdict, items: ev.evidence } : null
    const idle = d.column === 'ready' || d.column === 'backlog'
    const reason = ev && idle ? `Work already exists (${ev.verdict === 'in-flight' ? 'in flight' : 'commit mentions it'}: ${ev.evidence[0].ref}) - ${d.reason}` : d.reason
    const card = {
      number: issue.number,
      title: issue.title,
      url: issue.url,
      labels: names,
      tags: names.map((name) => ({ name, kind: labelKind(name) })),
      claimedBy: names.find((l) => l.startsWith('claimed:'))?.slice('claimed:'.length) || null,
      blockedBy: openDependencies(issue, openNumbers, ignored),
      heldDependencies: dependencyRefs(issue).filter((n) => heldNumbers.has(n)),
      notPlannedDependencies: dependencyRefs(issue).filter((n) => notPlannedNumbers.has(n)),
      held: !!d.held,
      progress: checklistProgress(issue.body),
      createdAt: issue.createdAt,
      closedAt: issue.closedAt || null,
      ageDays: Number.isFinite(created) ? Math.floor((now - created) / DAY_MS) : null,
      reason,
      evidence,
      owner: d.owner,
      prs: d.prs,
      hasTimeline: events.length > 0,
      isLive: liveNumbers.has(issue.number),
      revisit: null
    }
    // Add revisit information for held tickets
    if (names.includes('hold')) {
      card.revisit = latestRevisit(holdComments[issue.number] || [])
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
  const running = board.columns.some((c) => c.cards.some((k) => k.isLive))
  return { counts, archived, total, open: total - archived - (counts.done || 0), running }
}

// The record of what got done: every closed ticket (not just the last two weeks), newest first, grouped
// by month, with how long it took, its tags and the merged PR that closed it. Completed work stays
// useful as reference -- "how will we know where we are going if we don't remember where we have been".
export function buildCompleted({ issues, prs = [] }) {
  const prFor = new Map()
  for (const p of prs) {
    const n = parseTicketRef(p.body || '')
    if (n && !prFor.has(Number(n))) prFor.set(Number(n), { number: p.number, title: p.title, url: p.url, mergedAt: p.mergedAt || null })
  }
  const items = issues
    .filter((i) => i.state === 'CLOSED')
    .map((i) => {
      const created = Date.parse(i.createdAt)
      const closed = Date.parse(i.closedAt)
      return {
        number: i.number,
        title: i.title,
        url: i.url,
        tags: labelNames(i).map((name) => ({ name, kind: labelKind(name) })),
        labels: labelNames(i),
        createdAt: i.createdAt,
        closedAt: i.closedAt || null,
        tookDays: Number.isFinite(created) && Number.isFinite(closed) ? Math.max(0, Math.round((closed - created) / DAY_MS)) : null,
        pr: prFor.get(i.number) || null
      }
    })
    .sort((a, b) => (b.closedAt || '').localeCompare(a.closedAt || ''))
  const months = []
  for (const item of items) {
    const month = (item.closedAt || 'unknown').slice(0, 7)
    const last = months[months.length - 1]
    if (last && last.month === month) last.items.push(item)
    else months.push({ month, items: [item] })
  }
  return { items, months, total: items.length }
}
