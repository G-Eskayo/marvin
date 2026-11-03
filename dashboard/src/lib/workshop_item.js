// The Workshop's item page (#863): one page per unit of work, a ticket and its PRs, whichever you came from. Pure: it
// reads the same feed the Now view reads (workshop_feed.js) and the same next_step (ADR 0080, I4), so the page and its
// row in Now never disagree about whose move it is.
//
//   itemTarget(nav)               -> { repo, pr?, ticket? } | null   (what a link asks for; junk -> null)
//   resolveItem(target, value)    -> the ticket, its open PRs, the one that leads the page, and the lead's next step
//   lifeStages(resolved)          -> the life strip: Ticket → Look → Your answer → Build → Review → Merge → Shipped
//   historyRows(events, opts)     -> the ticket's stages, newest first (machine, how long, cost), then "Ticket opened"
//
// Cost: resolveItem builds Now once (O(T + P + Q)) and scans its items; the rest is linear in what it is given.
import { buildNow } from './next_step.js'
import { STAGE_LABEL, money } from './stage_strip.js'

const keyOf = (repo, number) => `${repo}#${number}`
const posInt = (v) => (Number.isInteger(v) && v > 0 ? v : typeof v === 'string' && /^\d+$/.test(v) && Number(v) > 0 ? Number(v) : null)

// A link's target: { tab: 'workshop', item: { repo, pr | ticket } }. A repo is "owner/name"; numbers are positive.
export function itemTarget(nav) {
  const t = nav?.item
  if (!t || typeof t !== 'object') return null
  const repo = typeof t.repo === 'string' && /^[^/\s]+\/[^/\s]+$/.test(t.repo) ? t.repo : null
  const pr = posInt(t.pr)
  const ticket = posInt(t.ticket)
  if (!repo || (pr == null && ticket == null)) return null
  return { repo, ...(pr != null ? { pr } : {}), ...(ticket != null ? { ticket } : {}) }
}

// One string per target, for "is this the same page".
export const targetKey = (t) => (t ? `${t.repo}|${t.pr ?? ''}|${t.ticket ?? ''}` : '')

// The PR that leads a ticket with more than one open: the first whose move is the owner's, else the lowest number.
function leadOf(prs, stepOf) {
  return prs.find((p) => stepOf(p)?.owner === 'owner') || prs[0] || null
}

// value: the Now feed's value ({ prs, tickets, projects, running, queue, proposals, machines }) plus `events`.
export function resolveItem(target, value = {}, now = Date.now()) {
  if (!target) return null
  const { repo } = target
  const arr = (v) => (Array.isArray(v) ? v : [])
  const prs = arr(value.prs)
  const tickets = arr(value.tickets)
  const built = buildNow({ ...value, prs, tickets, projects: arr(value.projects), running: arr(value.running), queue: arr(value.queue), proposals: arr(value.proposals),
    events: value.events instanceof Map ? value.events : new Map() }, now)
  const prItem = (n) => built.items.find((i) => i.type === 'pr' && i.repo === repo && i.number === n) || null

  const targetPr = target.pr != null ? prs.find((p) => p.repo === repo && p.number === target.pr) || null : null
  let ticketNumber = target.ticket ?? null
  if (ticketNumber == null && targetPr?.ticketRef != null) ticketNumber = Number(targetPr.ticketRef)
  // A board pairs a ticket with a PR the PR's own body didn't name (ticket.prs).
  if (ticketNumber == null && target.pr != null) ticketNumber = tickets.find((t) => t.repo === repo && (t.prs || []).includes(target.pr))?.number ?? null
  const ticket = ticketNumber != null ? tickets.find((t) => t.repo === repo && t.number === ticketNumber) || null : null

  const ofTicket = (p) => ticketNumber != null && (Number(p.ticketRef) === ticketNumber || (ticket?.prs || []).includes(p.number))
  const openPrs = prs.filter((p) => p.repo === repo && (p.number === target.pr || ofTicket(p))).sort((a, b) => a.number - b.number)
  const pr = target.pr != null ? targetPr : leadOf(openPrs, (p) => prItem(p.number)?.step)
  // The PR asked for isn't open (merged or closed): the page reads it on its own, read-only.
  const closedPr = target.pr != null && !targetPr ? target.pr : null

  // The next step that leads the page: the open PR's, else the ticket's own (a closed PR's ticket may still be open).
  const ticketKey = ticketNumber != null ? keyOf(repo, ticketNumber) : null
  const lead = (pr && prItem(pr.number)) ||
    (ticketKey && built.items.find((i) => i.type === 'ticket' && i.key === ticketKey)) ||
    (ticketKey && built.items.find((i) => i.covers?.includes(ticketKey))) || null
  return {
    repo, target, ticketNumber, ticket, pr, prs: openPrs, others: openPrs.filter((p) => p !== pr), closedPr,
    item: lead, step: lead?.step || null, project: lead?.project || (repo ? repo.split('/').pop() : null),
    title: ticket?.title || pr?.title || null
  }
}

// The bar's words: what the owner (or MARVIN) does next. "Answer 3 decisions, then approve" when an approve follows.
export function barText(step, pr) {
  if (!step) return null
  if (/^Answer \d+ decisions?$/.test(step.verb) && pr && pr.canMerge !== false) return `${step.verb}, then approve`
  return step.verb
}

// Who the bar names, and its tone: the Now view's own section names.
export function barWho(step) {
  if (!step) return { label: 'Not open', tone: 'closed' }
  if (step.section === 'stuck') return { label: 'Stuck', tone: 'stuck' }
  if (step.owner === 'owner') return { label: 'Your move', tone: 'yours' }
  if (step.section === 'next') return { label: 'Up next', tone: 'marvin' }
  if (step.owner === 'marvin') return { label: 'MARVIN is on it', tone: 'marvin' }
  return { label: 'Waiting', tone: 'waiting' }
}

export const LIFE = [
  ['ticket', 'Ticket'],
  ['look', 'Look'],
  ['answer', 'Your answer'],
  ['build', 'Build'],
  ['review', 'Review'],
  ['merge', 'Merge'],
  ['shipped', 'Shipped']
]

const isLook = (pr) => !!(pr?.mockups?.length) || /^mock-?up\b/i.test(pr?.title || '')
const BUILD_VERBS = new Set(['Building your answers', 'Being fixed', 'Sent back', 'Fixing a conflict', 'Building', 'No movement', 'Build failed', 'Rework', 'Act on your answers'])

// Which stage is lit now. `merged` (a PR read from history) and a closed ticket count as Shipped: Shipped is where
// MR Review's Merged list goes (plan "Projects and Shipped") until the ship step (I4) reports where it is live.
export function currentStage({ step, pr, closedPrState = null, ticketState = null }) {
  if (closedPrState === 'MERGED' || pr?.state === 'MERGED') return 'shipped'
  const verb = step?.verb || ''
  if (pr) {
    if (verb === 'Merging' || verb === 'In the merge queue') return 'merge'
    if (/^Answer \d+ decision/.test(verb) || verb === 'Send back for options') return 'answer'
    if (isLook(pr)) return verb === 'Approve the look' ? 'answer' : 'look'
    if (BUILD_VERBS.has(verb)) return 'build'
    return 'review'
  }
  if (!step) return ticketState === 'CLOSED' ? 'shipped' : 'ticket'
  if (verb === 'Give info') return 'answer'
  if (verb === 'Checks running') return 'review'
  if (verb === 'Shipping') return 'merge'
  if (BUILD_VERBS.has(verb)) return 'build'
  return 'ticket'
}

// The strip: a stage before the lit one is done when it happened, else skipped (not drawn as done: truthful). Look
// happened when the PR is a mock-up; Your answer when the PR or ticket asked Decisions. `seen` is the PR the page shows
// (open or read from history). The lit stage carries the bar's tone; the rest are still to come.
export function lifeStages(args) {
  const cur = currentStage(args)
  const at = LIFE.findIndex(([id]) => id === cur)
  const tone = cur === 'shipped' ? 'done' : barWho(args.step).tone
  const seen = args.seen ?? args.pr ?? null
  const happened = { look: isLook(seen), answer: !!(seen?.decisions?.present || args.ticketDecisions) }
  return LIFE.map(([id, label], i) => ({ id, label, tone: i === at ? tone : null,
    state: i === at ? 'now' : i > at ? 'later' : id in happened && !happened[id] ? 'skipped' : 'done' }))
}

const ms = (iso) => {
  const t = Date.parse(iso)
  return Number.isFinite(t) ? t : null
}
function took(fromMs, toMs) {
  if (fromMs == null || toMs == null || toMs < fromMs) return null
  const m = Math.round((toMs - fromMs) / 60_000)
  if (m < 1) return null
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  return h < 48 ? `${h} h ${m % 60 ? `${m % 60} min` : ''}`.trim() : `${Math.floor(h / 24)} d`
}

// The ticket's stages, newest first: "Build passed · Mac mini · 22 min · $0.41", its time on the right. How long a
// stage took is the gap since the stage before it. The last row is the ticket being opened, when that time is known.
export function historyRows(events = [], { machines = {}, ticketCreatedAt = null } = {}) {
  const list = (Array.isArray(events) ? events : []).filter((e) => e && ms(e.timestamp) != null)
  const rows = list.map((e, i) => {
    const prev = i > 0 ? ms(list[i - 1].timestamp) : null
    const name = e.machine ? (typeof machines[e.machine] === 'string' && machines[e.machine]) || e.machine : null
    const label = `${STAGE_LABEL[e.stage] || e.stage || 'Step'}${e.status && e.status !== 'passed' ? ` ${e.status}` : ''}`
    const parts = [label, name, e.status === 'running' ? null : took(prev, ms(e.timestamp)), e.cost_usd ? money(e.cost_usd) : null].filter(Boolean)
    return { at: ms(e.timestamp), text: parts.join(' · '), status: e.status || null, detail: e.detail || null }
  }).reverse()
  const opened = ms(ticketCreatedAt)
  if (opened != null) rows.push({ at: opened, text: 'Ticket opened', status: null, detail: null })
  return rows
}

// "pinned to a1c9f04": the one full commit every image is pinned to (I1), else null.
export function pinnedSha(images = []) {
  const shas = new Set()
  for (const img of images || []) {
    const m = /\/([0-9a-f]{40})\//.exec(img?.url || '')
    if (!m) return null
    shas.add(m[1])
  }
  return shas.size === 1 ? [...shas][0].slice(0, 7) : null
}
