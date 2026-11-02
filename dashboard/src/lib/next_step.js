// next_step (ADR 0080, rule I4): for every open ticket, PR and proposal, one next owner, one action verb and the
// section of the Workshop's Now view it belongs in. The smallest real version the Now view needs (#862); #860 grows
// this module (priority/since for the pipeline, a Python twin, `marvin next`) rather than replacing it.
//
// Pure: no React, no IPC. Every fact is one the dashboard already reads:
//   PRs        MR Review's cards (mr:list): describePrState's kind (prState.js) and the merge queue's line
//              (webhook-server/merge_order.js mergeOrder, carried as pr.mergeQueue: unbuilt answers, conflicts, place).
//   tickets    the boards' open tickets (activity:openTickets): labels and the column/reason board.js derives
//              (claimed:*, sent back, pipeline failed, stale claim, blocked, hold, ready-for-agent/-human, needs-info).
//   in motion  ticket_queue.py's running list (queue:list .running, with its machine) and each ticket's stage events
//              (activity:timeline), drawn by stage_strip.js's deriveStageStrip.
//   up next    ticket_queue.py's ready queue (queue:list .queue), already in ticket_pipeline._order_key order.
//   proposals  lib/proposals.py's open list (proposals:list).
//
//   nextStep(item, ctx) -> { owner: 'owner' | 'marvin' | 'nobody', verb, section, phase, stuckSince? }
//   buildNow(sources, now) -> { items, sections: {stuck, yours, marvin, next, waiting}, count }
//
// Sections: stuck (nobody's move, or MARVIN's step over its limit, I5) · yours · marvin (in motion) · next (the
// pipeline's ready queue) · waiting (blocked, held or not triaged: not shown in Now; see the PR's Decisions).
// Cost: O(T + P + Q) to build, then a sort per section.
import { describePrState } from './prState.js'
import { deriveStageStrip } from './stage_strip.js'

export const SECTIONS = ['stuck', 'yours', 'marvin', 'next', 'waiting']
// I5: MARVIN's stuck steps restart after 30 min.
export const MARVIN_STUCK_MS = 30 * 60_000

const PRIORITY_RE = /^(?:priority:)?(p[0-3])$/
export function priorityOf(labels = []) {
  for (const l of labels) {
    const m = PRIORITY_RE.exec(String(l))
    if (m) return m[1]
  }
  return null
}
const priorityRank = (p) => (p ? Number(p[1]) : 4)

const keyOf = (repo, number) => `${repo}#${number}`
const ms = (iso) => {
  const t = Date.parse(iso)
  return Number.isFinite(t) ? t : null
}
const lastAt = (events) => (events?.length ? ms(events[events.length - 1].timestamp) : null)
// When the current run began: the latest 'claimed' event, else the first event.
function runStart(events) {
  if (!events?.length) return null
  for (let i = events.length - 1; i >= 0; i--) if (events[i].stage === 'claimed') return ms(events[i].timestamp)
  return ms(events[0].timestamp)
}

const BUILD = new Set(['claimed', 'planning', 'executing'])
const REVIEW = new Set(['verifying', 'gate', 'merging'])
// The word at the right of an in-motion row (mock-up: build · review · ship), from the stage running now.
export function phaseOf(events) {
  const s = events?.length ? events[events.length - 1].stage : null
  if (!s || BUILD.has(s)) return 'build'
  if (REVIEW.has(s)) return 'review'
  return 'ship'
}

// One ticket's next step. ctx: { live: Map<key, {machine}>, events: Map<key, events[]>, queued: Map<key, position>, now }
export function ticketStep(t, ctx = {}) {
  const now = ctx.now ?? Date.now()
  const labels = new Set(t.labels || [])
  const key = keyOf(t.repo, t.number)
  const events = ctx.events?.get(key) || []
  const live = ctx.live?.get(key) || null
  const reason = t.reason || ''
  const step = (owner, verb, section, extra = {}) => ({ owner, verb, section, phase: null, ...extra })

  // Owner decisions nobody acted on (lib/owner_decisions.py files these once they are already overdue).
  if (labels.has('owner-decisions') && !labels.has('hold')) return step('marvin', 'Act on your answers', 'stuck', { stuckSince: ms(t.createdAt) })
  if (labels.has('hold')) return step('nobody', 'On hold', 'waiting')
  if (live || t.column === 'progress') {
    const moved = lastAt(events) ?? ms(t.updatedAt)
    if (moved != null && now - moved > MARVIN_STUCK_MS) return step('marvin', 'No movement', 'stuck', { stuckSince: moved })
    return step('marvin', 'Building', 'marvin', { phase: phaseOf(events) })
  }
  // In the pipeline's ready queue (ticket_queue.py): it runs next, even after a failed run (the retry is the queue's).
  const pos = ctx.queued?.get(key)
  if (pos != null) return step('marvin', pos === 1 ? 'Next' : 'Ready', 'next')
  if (t.column === 'blocked') {
    if (/^Pipeline failed/.test(reason)) return step('marvin', 'Build failed', 'stuck', { stuckSince: lastAt(events) ?? ms(t.updatedAt) })
    if (/no activity for/.test(reason)) return step('marvin', 'No movement', 'stuck', { stuckSince: lastAt(events) ?? ms(t.updatedAt) })
    if (/^Sent back/.test(reason)) return step('marvin', 'Rework', 'next')
    return step('nobody', 'Blocked', 'waiting')
  }
  if (t.column === 'review') {
    // The pipeline is past the build with no PR open yet (a PR, when open, carries the ticket instead).
    const phase = phaseOf(events)
    return step('marvin', phase === 'ship' ? 'Shipping' : 'Checks running', 'marvin', { phase })
  }
  if (labels.has('needs-info')) return step('owner', 'Give info', 'yours')
  if (labels.has('ready-for-human')) return step('owner', 'Your task', 'yours')
  if (labels.has('ready-for-agent')) return step('marvin', 'Ready', 'next')
  return step('nobody', labels.has('needs-triage') ? 'Needs triage' : 'Not triaged', 'waiting')
}

// One PR's next step, from MR Review's own ranking (describePrState) and the merge queue's line.
export function prStep(pr, ctx = {}) {
  const now = ctx.now ?? Date.now()
  const mq = pr.mergeQueue || null
  const kind = describePrState(pr).kind
  const ticketKey = pr.ticketRef != null ? keyOf(pr.repo, pr.ticketRef) : null
  const live = ticketKey ? ctx.live?.get(ticketKey) : null
  const events = ticketKey ? ctx.events?.get(ticketKey) || [] : []
  const step = (owner, verb, section, extra = {}) => ({ owner, verb, section, phase: null, ...extra })
  const mine = (verb, phase) => {
    if (live) {
      const moved = lastAt(events)
      if (moved != null && now - moved > MARVIN_STUCK_MS) return step('marvin', 'No movement', 'stuck', { stuckSince: moved })
    }
    return step('marvin', verb, 'marvin', { phase })
  }

  if (kind === 'merging') return mine('Merging', 'ship')
  if (kind === 'in-queue') return mine('In the merge queue', 'ship')
  if (kind === 'sent-back') return mine(live ? 'Being fixed' : 'Sent back', 'build')
  if (kind === 'ticket-closed') return step('owner', 'Close it', 'yours')
  if (kind === 'conflict') {
    if (/needs a rebuild/.test(mq?.reason || '')) return step('nobody', 'Needs a rebuild', 'stuck', { stuckSince: ms(pr.createdAt) })
    return mine('Fixing a conflict', 'review')
  }
  if (kind === 'checks-failed') return mine('Being fixed', 'build')
  if (kind === 'needs-images') return mine('Adding images', 'review')
  if (kind === 'needs-options') return step('owner', 'Send back for options', 'yours')
  if (kind === 'decisions-pending') {
    const n = pr.decisions?.pending?.length || 0
    return step('owner', `Answer ${n} decision${n === 1 ? '' : 's'}`, 'yours')
  }
  if (mq?.unbuilt) return mine('Building your answers', 'build')
  if (kind === 'waiting-checks') return mine('Checks running', 'review')
  if (kind === 'wrong-base') return step('owner', 'Change the base', 'yours')
  if (kind === 'error' || kind === 'tests-after-rebase') return step('owner', 'Approve again', 'yours')
  if (kind === 'ready' || kind === 'stacked') return step('owner', pr.mockups?.length ? 'Approve the look' : 'Approve', 'yours')
  return step('owner', 'Look at it', 'yours')
}

export function proposalStep() {
  return { owner: 'owner', verb: 'Weigh a proposal', section: 'yours', phase: null }
}

export function nextStep(item, ctx = {}) {
  if (item.type === 'pr') return prStep(item.pr, ctx)
  if (item.type === 'ticket') return ticketStep(item.ticket, ctx)
  if (item.type === 'proposal') return proposalStep(item.proposal, ctx)
  return { owner: 'nobody', verb: 'Unknown', section: 'waiting', phase: null }
}

// The project chip: the catalog id for the repo, else the repo's own name (a project with no catalog id).
export function projectChip(repo, projects = []) {
  const p = (projects || []).find((x) => x.repo === repo)
  return p?.id || (repo ? String(repo).split('/').pop() : null)
}

const sortBy = (fns) => (a, b) => {
  for (const f of fns) {
    const d = f(a, b)
    if (d) return d
  }
  return 0
}
const sinceAsc = (a, b) => (a.since ?? Infinity) - (b.since ?? Infinity)

// sources: { prs, tickets, projects, running, queue, proposals, events: Map<key, events[]> }. Any may be missing.
// Every open ticket is one item, unless an open PR closes it: then the PR's item carries it (`covers`).
export function buildNow(sources = {}, now = Date.now()) {
  const { prs = [], tickets = [], projects = [], running = [], queue = [], proposals = [], events = new Map() } = sources
  const live = new Map(running.map((r) => [keyOf(r.repo, r.number), r]))
  // The queue can list a ticket twice (a repo read twice); its place is its first.
  const queued = new Map()
  for (const r of queue) {
    const k = keyOf(r.repo, r.number)
    if (!queued.has(k) || r.position < queued.get(k)) queued.set(k, r.position)
  }
  const ctx = { live, events, queued, now }
  const ticketByKey = new Map(tickets.map((t) => [keyOf(t.repo, t.number), t]))
  const items = []
  const covered = new Set()

  for (const pr of prs) {
    const ticketKey = pr.ticketRef != null ? keyOf(pr.repo, pr.ticketRef) : null
    const ticket = ticketKey ? ticketByKey.get(ticketKey) : null
    if (ticket) covered.add(ticketKey)
    const item = { type: 'pr', key: pr.key || keyOf(pr.repo, pr.number), repo: pr.repo, number: pr.number, title: pr.title, url: pr.url, pr,
      ticketNumber: pr.ticketRef ?? null, covers: ticket ? [ticketKey] : [], priority: priorityOf(ticket?.labels), since: ms(pr.createdAt),
      worker: ticketKey ? live.get(ticketKey)?.machine || null : null, events: ticketKey ? events.get(ticketKey) || [] : [] }
    items.push(item)
  }
  // Tickets a board pairs with an open PR (closes it) that MR Review's list didn't pair by its body.
  const prNumbers = new Set(prs.map((p) => keyOf(p.repo, p.number)))
  for (const t of tickets) {
    const key = keyOf(t.repo, t.number)
    if (covered.has(key)) continue
    if ((t.prs || []).some((n) => prNumbers.has(keyOf(t.repo, n)))) {
      const host = items.find((i) => i.type === 'pr' && i.repo === t.repo && (t.prs || []).includes(i.number))
      host.covers.push(key)
      if (!host.priority) host.priority = priorityOf(t.labels)
      covered.add(key)
      continue
    }
    items.push({ type: 'ticket', key, repo: t.repo, number: t.number, title: t.title, url: t.url, ticket: t, covers: [key],
      priority: priorityOf(t.labels), since: ms(t.createdAt), worker: live.get(key)?.machine || null, events: events.get(key) || [],
      position: queued.get(key) ?? null })
  }
  // A ticket running or queued that the boards didn't list (a project whose board failed to load): still shown.
  for (const r of [...running, ...queue]) {
    const key = keyOf(r.repo, r.number)
    if (covered.has(key) || items.some((i) => i.type === 'ticket' && i.key === key)) continue
    const ticket = { repo: r.repo, number: r.number, title: r.title, labels: [live.has(key) ? `claimed:${r.machine}` : 'ready-for-agent', ...(r.priority ? [r.priority] : [])], createdAt: r.createdAt || null, column: live.has(key) ? 'progress' : 'ready' }
    items.push({ type: 'ticket', key, repo: r.repo, number: r.number, title: r.title, url: null, ticket, covers: [key], priority: priorityOf(ticket.labels),
      since: ms(r.createdAt), worker: live.get(key)?.machine || null, events: events.get(key) || [], position: queued.get(key) ?? null })
  }
  for (const p of proposals) {
    items.push({ type: 'proposal', key: `proposal:${p.id}`, repo: null, number: null, title: p.title, proposal: p, covers: [],
      priority: null, since: ms(p.added), worker: null, events: [] })
  }

  for (const item of items) {
    item.step = nextStep(item, ctx)
    item.project = item.repo ? projectChip(item.repo, projects) : null
    item.startedAt = item.step.section === 'marvin' ? runStart(item.events) : null
  }

  const sections = Object.fromEntries(SECTIONS.map((s) => [s, items.filter((i) => i.step.section === s)]))
  sections.stuck.sort(sortBy([(a, b) => (a.step.stuckSince ?? Infinity) - (b.step.stuckSince ?? Infinity)]))
  sections.yours.sort(sortBy([(a, b) => priorityRank(a.priority) - priorityRank(b.priority), sinceAsc]))
  sections.marvin.sort(sortBy([(a, b) => (a.startedAt ?? Infinity) - (b.startedAt ?? Infinity), sinceAsc]))
  sections.next.sort(sortBy([(a, b) => (a.position ?? Infinity) - (b.position ?? Infinity), (a, b) => priorityRank(a.priority) - priorityRank(b.priority), sinceAsc]))
  return { items, sections, count: sections.yours.length }
}

// The stage strip under an in-motion row: the existing derivation (stage_strip.js), drawn as thin bars.
export function stripFor(item, now = Date.now()) {
  if (!item.events?.length) return []
  return deriveStageStrip(item.events, { now, liveOverlay: { isLiveNow: !!item.worker } }).map((s) => s.status)
}

// "6 h", "40 min", "3 d": the wait or run length the mock-up shows.
export function durationText(fromMs, now = Date.now()) {
  if (fromMs == null) return null
  const m = Math.max(0, Math.floor((now - fromMs) / 60_000))
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  if (h < 48) return `${h} h`
  return `${Math.floor(h / 24)} d`
}
