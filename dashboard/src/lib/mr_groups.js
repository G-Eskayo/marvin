// MR Review by project (marvin#758): which project each open PR belongs to, the order inside a group, and the
// group-level state the screen remembers (collapsed, scroll place, history step). Pure: the list in, the groups out,
// derived again on every refresh, never stored.
//
// A PR belongs to its repo's project unless it carries `project:<catalog id>` (ADR 0060), the same rule the boards
// use. A PR whose project can't be worked out goes to Other with the reason, so it is seen and fixed, never dropped.

import { describePrState } from './prState.js'
import { projectIdOf } from './projects.js'

export const OTHER = 'other'

// Display order. "Needs you" first, as the ticket asks; "stuck" holds PRs being fixed somewhere else (sent back,
// conflicts, failing checks, missing images), which neither you nor time will move on their own.
export const TIERS = [
  { id: 'needs-you', label: 'Needs you' },
  { id: 'running', label: 'Checks running' },
  { id: 'waiting', label: 'Waiting on another PR' },
  { id: 'stuck', label: 'Being fixed' },
  { id: 'draft', label: 'Draft' }
]
const TIER_RANK = Object.fromEntries(TIERS.map((t, i) => [t.id, i]))

// describePrState's kinds, in order inside their tier. Unknown kinds sort last in "stuck" so a new state is visible.
const KIND_ORDER = [
  // needs you: answer, approve, approve again, then the cleanups only you can do
  ['decisions-pending', 'needs-you'], ['ready', 'needs-you'], ['tests-after-rebase', 'needs-you'],
  ['interrupted', 'needs-you'], ['error', 'needs-you'], ['needs-options', 'needs-you'], ['ticket-closed', 'needs-you'],
  ['merging', 'running'], ['waiting-checks', 'running'], ['github-outage', 'running'],
  ['stacked', 'waiting'], ['in-queue', 'waiting'], // marvin#231: approved, in the merge queue
  ['sent-back-now', 'stuck'], ['sent-back', 'stuck'], ['conflict', 'stuck'], ['checks-failed', 'stuck'],
  ['needs-images', 'stuck'], ['wrong-base', 'stuck']
]
const KIND_TIER = Object.fromEntries(KIND_ORDER)
const KIND_RANK = Object.fromEntries(KIND_ORDER.map(([k], i) => [k, i]))

const labelNames = (pr) => (pr.labels || []).map((l) => (typeof l === 'string' ? l : l?.name)).filter(Boolean)
// The repo comes from the PR itself (its repo field, else its URL), never a hard-coded owner (lib/tests/test_instance.py).
const repoOf = (pr) => pr.repo || /github\.com\/([^/]+\/[^/]+)\/pull\//.exec(pr.url || '')?.[1] || ''

export function projectOfPr(pr, projects) {
  const list = Array.isArray(projects) ? projects : []
  const ids = new Set(list.map((p) => p.id))
  const wanted = [...new Set(labelNames(pr).filter((n) => n.startsWith('project:')).map((n) => n.slice('project:'.length)))]
  if (wanted.length > 1) return { id: OTHER, why: 'two-labels' }
  if (wanted.length === 1) return ids.has(wanted[0]) ? { id: wanted[0], why: 'label' } : { id: OTHER, why: 'unknown-label' }
  const repo = repoOf(pr).toLowerCase()
  const byRepo = list.find((p) => p.repo && p.repo.toLowerCase() === repo)
  if (byRepo) return { id: byRepo.id, why: 'repo' }
  const slug = projectIdOf(repo)
  if (ids.has(slug)) return { id: slug, why: 'repo' }
  return { id: OTHER, why: 'unknown-repo' }
}

const kindOf = (pr, status) => describePrState(pr, { status: status || 'idle' }).kind

export function tierOf(pr, { status = 'idle' } = {}) {
  if (pr.isDraft) return 'draft'
  return KIND_TIER[kindOf(pr, status)] || 'stuck'
}

function rankOf(pr, statusOf) {
  const status = statusOf(pr)
  const kind = kindOf(pr, status)
  const tier = pr.isDraft ? 'draft' : KIND_TIER[kind] || 'stuck'
  return [TIER_RANK[tier], KIND_RANK[kind] ?? KIND_ORDER.length]
}

export function sortPrs(prs, { statusOf = () => 'idle' } = {}) {
  const ranked = prs.map((pr) => ({ pr, r: rankOf(pr, statusOf) }))
  ranked.sort((a, b) => a.r[0] - b.r[0] || a.r[1] - b.r[1] || a.pr.number - b.pr.number || repoOf(a.pr).localeCompare(repoOf(b.pr)))
  return ranked.map((x) => x.pr)
}

const byName = (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })

// empty: 'hide' (default) or 'show' (catalog projects with a repo and no open PR, as empty groups after the rest).
// isLive(project): which catalog projects count for 'show' (active ones; archived boards stay out).
export function groupPrs(prs, projects, { empty = 'hide', isLive = () => true, statusOf = () => 'idle' } = {}) {
  const list = Array.isArray(projects) ? projects : []
  const buckets = new Map()
  for (const pr of prs) {
    const { id, why } = projectOfPr(pr, list)
    if (!buckets.has(id)) buckets.set(id, [])
    buckets.get(id).push(id === OTHER ? { ...pr, groupWhy: why } : pr)
  }
  if (empty === 'show') {
    for (const p of list) if (p.repo && isLive(p) && !buckets.has(p.id)) buckets.set(p.id, [])
  }
  const groups = [...buckets].map(([id, members]) => {
    const sorted = sortPrs(members, { statusOf })
    const project = list.find((p) => p.id === id)
    return {
      id,
      name: id === OTHER ? 'Other' : project?.name || id,
      prs: sorted,
      count: sorted.length,
      needsYou: sorted.filter((pr) => tierOf(pr, { status: statusOf(pr) }) === 'needs-you').length
    }
  })
  const other = groups.filter((g) => g.id === OTHER)
  const rest = groups.filter((g) => g.id !== OTHER)
  rest.sort((a, b) => b.needsYou - a.needsYou || b.count - a.count || byName(a, b))
  return [...rest, ...other]
}

// "All": today's list, kept as it is (the ticket: nothing is lost). sort: true gives it the new order instead.
export function allView(prs, { sort = false, statusOf } = {}) {
  return sort ? sortPrs(prs, { statusOf }) : [...prs]
}

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

export function needsYouSummary(prs) {
  if (!prs.length) return 'no open MRs'
  const kinds = prs.map((pr) => ({ tier: tierOf(pr), kind: pr.isDraft ? 'draft' : kindOf(pr) }))
  const mine = kinds.filter((k) => k.tier === 'needs-you')
  if (mine.length) {
    const dec = mine.filter((k) => k.kind === 'decisions-pending').length
    const approve = mine.filter((k) => k.kind === 'ready').length
    const rest = mine.length - dec - approve
    return [dec && plural(dec, 'decision'), approve && `${approve} to approve`, rest && `${rest} other`].filter(Boolean).join(' · ')
  }
  const count = (t) => kinds.filter((k) => k.tier === t).length
  const parts = [['running', 'running'], ['waiting', 'waiting'], ['stuck', 'being fixed'], ['draft', 'draft']]
    .map(([t, word]) => (count(t) ? `${count(t)} ${word === 'draft' && count(t) > 1 ? 'drafts' : word}` : null))
    .filter(Boolean)
  return ['nothing for you', ...parts].join(' · ')
}

// Collapsed or open. saved: { [groupId]: boolean } (what you chose, remembered); rule: the default before you choose:
// 'open' everything open, 'big' over `limit` PRs collapsed, 'quiet' nothing for you collapsed. Empty is always collapsed.
export function isCollapsed(group, saved = {}, { rule = 'open', limit = 8 } = {}) {
  if (!group.count) return true
  if (Object.prototype.hasOwnProperty.call(saved, group.id)) return !!saved[group.id]
  if (rule === 'big') return group.count > limit
  if (rule === 'quiet') return group.needsYou === 0
  return false
}

export function toggleCollapsed(saved, group, opts) {
  return { ...saved, [group.id]: !isCollapsed(group, saved, opts) }
}

// The value for useScrollPlace (#755): each view, and each group opened on its own, keeps its own place.
export function placeValue({ grouping, focus = null }) {
  if (grouping !== 'project') return 'all'
  return focus ? `project:${focus}` : 'project'
}

// The item for the dashboard's one history (#756): a group opened on its own is a step, so swipe back leaves it.
export function historyItem({ grouping, focus = null }) {
  return grouping === 'project' && focus ? `project:${focus}` : null
}

// Between two groupings of the list: what left, which groups went or came, and which PRs changed group or tier, for the
// merge motion (#757) to animate instead of jumping.
export function diffGroups(before, after) {
  const where = (groups) => {
    const m = new Map()
    for (const g of groups) for (const pr of g.prs) m.set(pr.key, { group: g.id, tier: tierOf(pr) })
    return m
  }
  const was = where(before)
  const now = where(after)
  const left = [...was].filter(([k]) => !now.has(k)).map(([key, w]) => ({ key, group: w.group }))
  const moved = [...now]
    .filter(([k, n]) => was.has(k) && (was.get(k).group !== n.group || was.get(k).tier !== n.tier))
    .map(([key, to]) => ({ key, from: was.get(key), to }))
  const beforeIds = before.map((g) => g.id)
  const afterIds = after.map((g) => g.id)
  const kept = beforeIds.filter((id) => afterIds.includes(id))
  const keptAfter = afterIds.filter((id) => beforeIds.includes(id))
  return {
    left,
    groupsGone: beforeIds.filter((id) => !afterIds.includes(id)),
    groupsNew: afterIds.filter((id) => !beforeIds.includes(id)),
    moved,
    reordered: kept.join('\n') !== keptAfter.join('\n')
  }
}

// The helper tab working on a PR (helper-tab titles: "● <group> · <title>", marvin#753). tabs: [{ state, group, title }]
// as helper_tab.parse_title gives them. A match is "#<PR or ticket number>" as a whole number in the title, in a tab
// whose group is one of this project's names (a name or a list: catalog id, catalog name, the name helpers are started
// under). A running tab wins over a finished one.
const MARKS = { running: '●', done: '✓', failed: '✗' }
const norm = (s) => String(s || '').toLowerCase().split(/\s+/).filter(Boolean).join(' ')

export function helperFor(pr, projectNames, tabs) {
  if (!Array.isArray(tabs) || !tabs.length) return null
  const names = new Set((Array.isArray(projectNames) ? projectNames : [projectNames]).map(norm))
  const nums = [pr.number, pr.ticketRef].filter((n) => n != null).map(String)
  const has = (title, n) => new RegExp(`#${n}(?!\\d)`).test(title)
  const mine = tabs.filter((t) => names.has(norm(t.group)) && nums.some((n) => has(t.title, n)))
  if (!mine.length) return null
  const t = mine.find((x) => x.state === 'running') || mine[mine.length - 1]
  return { state: t.state, label: `${MARKS[t.state] || '●'} ${t.group} · ${t.title}` }
}
