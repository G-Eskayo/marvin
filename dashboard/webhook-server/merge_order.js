import { ciState } from './ci_status.js'
import { summarizeDecisions, vagueness } from './decisions.js'

// The merge queue's order (marvin#231, decided with the owner 2026-10-30): for every open PR of one repo, whether it is
// queued and where, or what it waits for, as one plain line. Pure: the webhook's runner and MR Review (both Macs) call
// it with the same facts and get the same answer, and next_step() (#860) can read the reasons later.
//
//   mergeOrder(openPrs, mainState, queue) -> { entries: {url: entry}, order: [url], next: url|null, dropped: [url] }
//
// openPrs:   one repo's open PRs, enriched by enrichForOrder() (sentBack, decisionsUnbuilt, conflict, ...).
// mainState: mainStateFrom(): is the base branch red, and which open tickets fix it.
// queue:     { items: [{url, approvedAt, conflictHead?}], failed: {url: {reason}}, lastMerged: N|null, running: url|null }
//            conflictHead: the commit the gate found conflicting; held as a conflict until a new commit replaces it.
// entry:     { url, number, queued, state, tone, reason, position, waitsFor }
//   state: running | queued (its turn will come) | waiting (blocked, or waits for something) | ready (not approved,
//   nothing in the way: no line). tone: sky for queued/running, amber for waiting, null for ready.
//
// Rules: a stacked PR waits for the PR it is built on (base first: topological, then the order approved); while main is
// red only a PR that fixes it may go; a PR's own blockers (Decisions, unbuilt answers, failing checks, a conflict) are
// said before what it waits for, since they need doing whatever merges first. Cost: O(P + Q log Q) for P open PRs and
// Q queued ones.

export const FIX_TITLE = /\bmain\s+(?:is\s+)?red\b/i
const CLOSES_RE = /\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:([\w.-]+\/[\w.-]+))?#(\d+)/gi

const labelNames = (item) => (item?.labels || []).map((l) => (typeof l === 'string' ? l : l?.name)).filter(Boolean)

// Every ticket of this repo the PR says it closes ("Closes #N", "Fixes owner/repo#N"), in the order written.
export function closesRefs(body, repo = null) {
  const out = []
  for (const m of String(body || '').matchAll(CLOSES_RE)) {
    if (m[1] && repo && m[1].toLowerCase() !== String(repo).toLowerCase()) continue
    const n = Number(m[2])
    if (!out.includes(n)) out.push(n)
  }
  return out
}

// A ticket saying main is red: CI's own (label main-red, lib/main_red.py), or a hand-filed bug+p0 titled "Main red".
export function isRedTicket(issue) {
  const l = new Set(labelNames(issue))
  return l.has('main-red') || (l.has('bug') && l.has('priority:p0') && FIX_TITLE.test(issue?.title || ''))
}
// A PR closing one of these may go while main is red: a main-red ticket, or an incident.
export function isFixTicket(issue) {
  return isRedTicket(issue) || labelNames(issue).includes('incident')
}

// What MARVIN already knows about main: CI's open main-red ticket (lib/main_red.py) and, for marvin itself, the full
// suite on a clean main (lib/main_health.py, ~/.claude/logs/main-health.json, `health`).
export function mainStateFrom({ issues = [], health = null, base = 'main' } = {}) {
  const open = (issues || []).filter((i) => i && (!i.state || String(i.state).toUpperCase() === 'OPEN'))
  const byNumber = (a, b) => a - b
  const redTickets = open.filter(isRedTicket).map((i) => i.number).sort(byNumber)
  const fixTickets = open.filter(isFixTicket).map((i) => i.number).sort(byNumber)
  const healthRed = !!health && health.ok === false
  return { base, red: redTickets.length > 0 || healthRed, redTickets, fixTickets, healthRed }
}

// The facts mergeOrder reads off each PR, from what each side already has. One implementation for both.
//   issues: the repo's open tickets (labels) · unbuilt: Set of PR urls with answered-but-unbuilt Decisions
//   repairFailed: {"repo#n": headSha} whose conflict repair failed (lib/conflict_repair.py)
//   rebaseStatus: the post-merge conflict check by url (#225) · sentBack: Set of "repo#ticket" (optional)
export function enrichForOrder(prs, { repo = null, issues = [], unbuilt = new Set(), repairFailed = {}, rebaseStatus = {}, sentBack = null } = {}) {
  const sentBackTickets = sentBack || new Set((issues || []).filter((i) => labelNames(i).includes('needs-reengagement')).map((i) => `${repo}#${i.number}`))
  return (prs || []).map((p) => {
    const r = p.repo || repo
    const ticket = closesRefs(p.body, r)[0] ?? null
    const rb = rebaseStatus?.[p.url]
    const rbConflict = rb?.state === 'conflict'
    const conflict = p.mergeable === 'CONFLICTING' || (rbConflict && (!p.mergeable || p.mergeable === 'UNKNOWN'))
    return {
      ...p,
      repo: r,
      sentBack: p.sentBack ?? (ticket !== null && sentBackTickets.has(`${r}#${ticket}`)),
      decisionsUnbuilt: unbuilt.has(p.url),
      conflict,
      conflictAfter: rbConflict && Number.isFinite(rb.after) ? rb.after : null,
      repairFailed: !!p.headRefOid && repairFailed?.[`${r}#${p.number}`] === p.headRefOid
    }
  })
}

export function ordinal(n) {
  const t = n % 100
  if (t >= 11 && t <= 13) return `${n}th`
  return `${n}${({ 1: 'st', 2: 'nd', 3: 'rd' })[n % 10] || 'th'}`
}

const short = (s, max = 80) => {
  const one = String(s || '').replace(/\s+/g, ' ').trim()
  return one.length > max ? `${one.slice(0, max - 1)}…` : one
}

// What the PR itself needs before it can merge, whatever else merges first, or null.
function ownReason(pr, base) {
  const dec = summarizeDecisions(pr.body || '')
  if (vagueness(pr.body || '') || dec?.problems?.length) return { reason: 'asks you to choose without options' }
  if (dec?.pending?.length) {
    const n = dec.pending.length
    return { reason: `${n} Decision${n === 1 ? ' is' : 's are'} waiting for you` }
  }
  if (pr.decisionsUnbuilt) return { reason: "your answers aren't built yet", unbuilt: true }
  const ci = ciState(pr.statusCheckRollup)
  if (ci.state === 'failing') return { reason: `checks failing: ${ci.failing.join(', ')}` }
  if (pr.conflict) {
    const after = pr.conflictAfter ? ` after #${pr.conflictAfter}` : ''
    return { reason: `conflicts with ${base}${after} · ${pr.repairFailed ? 'needs a rebuild' : 'MARVIN is fixing it'}`, conflict: true }
  }
  if (pr.sentBack) return { reason: 'sent back for rework' }
  return null
}

// The parent each stacked PR is built on (another open PR whose head branch is its base), and every PR on a loop.
function stackOf(prs, base) {
  const byHead = new Map(prs.map((p) => [p.headRefName, p]))
  const parent = new Map()
  for (const p of prs) {
    if (!p.baseRefName || p.baseRefName === base) continue
    const up = byHead.get(p.baseRefName)
    parent.set(p.url, up && up.url !== p.url ? up : null)
  }
  const loop = new Map() // url -> the loop's numbers, in order
  for (const p of prs) {
    const seen = []
    let cur = p
    while (cur && parent.get(cur.url) && !seen.includes(cur.url)) {
      seen.push(cur.url)
      cur = parent.get(cur.url)
    }
    if (cur && seen.includes(cur.url)) {
      const ring = seen.slice(seen.indexOf(cur.url)).map((u) => prs.find((x) => x.url === u).number)
      for (const u of seen.slice(seen.indexOf(cur.url))) if (!loop.has(u)) loop.set(u, ring)
    }
  }
  return { parent, loop }
}

export function mergeOrder(openPrs, mainState, queue) {
  const prs = (openPrs || []).filter((p) => p && typeof p.url === 'string')
  const main = mainState || mainStateFrom()
  const base = main.base || 'main'
  const items = (queue?.items || []).filter((i) => i && typeof i.url === 'string')
  const failed = queue?.failed || {}
  const running = queue?.running || null
  const open = new Set(prs.map((p) => p.url))
  const queuedAt = new Map()
  const heldOn = new Map()
  for (const i of items) {
    if (!open.has(i.url) || queuedAt.has(i.url)) continue
    queuedAt.set(i.url, Number(i.approvedAt) || 0)
    if (i.conflictHead) heldOn.set(i.url, i.conflictHead)
  }
  const dropped = [...new Set(items.map((i) => i.url))].filter((u) => !open.has(u))

  const { parent, loop } = stackOf(prs, base)
  const fixes = new Set(main.fixTickets || [])
  const isFix = (p) => closesRefs(p.body, p.repo).some((n) => fixes.has(n))
  const fixPrs = prs.filter(isFix).sort((a, b) => a.number - b.number)
  const redWaitsFor = fixPrs[0]?.number ?? (main.redTickets || [])[0] ?? null

  const entries = {}
  for (const p of prs) {
    const queued = queuedAt.has(p.url)
    let why = null
    let waitsFor = null
    if (loop.has(p.url)) {
      const ring = loop.get(p.url)
      why = { reason: `its base PRs form a loop: ${[...ring, ring[0]].map((n) => `#${n}`).join(' → ')}` }
    } else if (parent.has(p.url) && parent.get(p.url) === null) {
      why = { reason: `targets ${p.baseRefName}, which has no open PR · change its base to ${base}` }
    }
    if (!why) {
      const held = heldOn.has(p.url) && heldOn.get(p.url) === p.headRefOid
      const after = p.conflictAfter ?? (held || p.conflict ? queue?.lastMerged ?? null : null)
      why = ownReason(held ? { ...p, conflict: true, conflictAfter: after } : { ...p, conflictAfter: after }, base)
    }
    if (!why && parent.get(p.url)) {
      const up = parent.get(p.url)
      waitsFor = up.number
      why = failed[up.url] ? { reason: `waits for #${up.number} (it failed: ${short(failed[up.url].reason, 60)})` } : { reason: `waits for #${up.number} (it's built on it)` }
    }
    if (!why && main.red && !isFix(p)) {
      waitsFor = redWaitsFor
      why = { reason: redWaitsFor ? `main is red · waits for #${redWaitsFor}` : 'main is red · waits for a fix' }
    }
    entries[p.url] = { url: p.url, number: p.number, queued, state: why ? 'waiting' : queued ? 'queued' : 'ready', tone: why ? 'amber' : queued ? 'sky' : null,
      reason: why?.reason || null, position: null, waitsFor, ...(why?.unbuilt ? { unbuilt: true } : {}), ...(why?.conflict ? { conflict: true } : {}) }
  }

  // Every queued PR in merge order: base before what is built on it (topological), then fixes for a red main first,
  // then the order approved, then the PR number. A loop's members have no base-first order; they keep approval order.
  const rank = (p) => [main.red && isFix(p) ? 0 : 1, queuedAt.get(p.url), p.number]
  const cmp = (a, b) => { const x = rank(a), y = rank(b); return x[0] - y[0] || x[1] - y[1] || x[2] - y[2] }
  const queuedPrs = prs.filter((p) => queuedAt.has(p.url))
  const inQueue = new Set(queuedPrs.map((p) => p.url))
  const order = []
  const placed = new Set()
  const pending = [...queuedPrs].sort(cmp)
  while (pending.length) {
    const i = pending.findIndex((p) => { const up = parent.get(p.url); return loop.has(p.url) || !up || !inQueue.has(up.url) || placed.has(up.url) })
    const [p] = pending.splice(i < 0 ? 0 : i, 1)
    order.push(p.url)
    placed.add(p.url)
  }

  // Positions count what will actually run, in turn: the merge running now first, then each queued PR with nothing in
  // its way.
  const runnable = order.filter((u) => entries[u].state === 'queued' && u !== running)
  const line = running && open.has(running) ? [running, ...runnable] : runnable
  line.forEach((u, i) => {
    const e = entries[u]
    e.position = i + 1
    if (u === running) Object.assign(e, { state: 'running', tone: 'sky', reason: 'merging now', queued: true })
    else e.reason = i === 0 ? `queued · ${ordinal(1)} · starts next` : `queued · ${ordinal(i + 1)} · starts after #${entries[line[i - 1]].number}`
  })
  const next = running && open.has(running) ? null : runnable[0] || null
  return { entries, order, next, dropped }
}
