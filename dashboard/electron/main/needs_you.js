import { dependencyRefs, openDependencies } from './board.js'
import { parseHumanTask } from '../../src/lib/human_task.js'

const DAY_MS = 86400_000

const HUMAN_TITLE_PATTERN = /\b(design session|decision|conversation|planning)\b|\s*:/i

// Sections that indicate "What to build", checking for common variations
function hasWhatToBuild(body) {
  return /##\s*(What to build|What|Summary|Description|Solution|Approach|Proposal|Design|Build|Problem|Convention)\b/i.test(body || '')
}

// Acceptance criteria: section with checkboxes
function hasAcceptanceCriteria(body) {
  return /##\s*Acceptance(?:\s+criteria)?\b[\s\S]*?-\s*\[[ xX]\]/i.test(body || '')
}

// How we'll try to break it section, excluding TBD/N/A fillers
function hasBreakIt(body) {
  const text = String(body || '').replace(/```[\s\S]*?```/g, '') // Remove code blocks

  // Find the heading line (supporting both straight and curly quotes, and "will" variants)
  const headingMatch = text.match(/^##\s*(?:How we(?:'|'|—|\s+wi)ll\s+(?:try\s+to\s+)?break\s+it|Misuse cases)\b.*$/im)
  if (!headingMatch) return false

  // Find the section content after the heading
  const headingEnd = headingMatch.index + headingMatch[0].length
  const rest = text.slice(headingEnd)

  // Find the next section heading or end
  const nextHeading = rest.match(/^##\s/m)
  const sectionEnd = nextHeading ? nextHeading.index : rest.length
  const section = rest.slice(0, sectionEnd)

  // Check for at least one real line (not just TBD/TODO/N/A fillers)
  const filler = /^(?:-\s*\[[ x]\]\s*)?(tbd|todo|n\/a|none|-+)\.?$/i
  const lines = section.split('\n')
  return lines.some((line) => {
    const trimmed = line.trim()
    return trimmed && !filler.test(trimmed)
  })
}

// What is missing from a ticket's sections to be triaged
export function missingFor(ticket) {
  const body = ticket.body || ''
  const title = ticket.title || ''
  const labels = new Set((ticket.labels || []).map((l) => l.name || l))

  // If it's a human-task-shaped title, use that logic
  if (HUMAN_TITLE_PATTERN.test(title)) {
    const parsed = parseHumanTask(body)
    return parsed.missing
  }

  const missing = []

  if (!hasWhatToBuild(body)) {
    missing.push('a "What to build" section')
  }

  if (!hasAcceptanceCriteria(body)) {
    missing.push('acceptance criteria')
  }

  // Only check for break-it if we have what/ac AND it's not research-labelled
  if (missing.length === 0 && !labels.has('research') && !hasBreakIt(body)) {
    missing.push('a "How we\'ll try to break it" section')
  }

  return missing
}

// Build a reverse-adjacency (blocks) graph for one repo, excluding held/not-planned
export function blocksGraph(tickets, repo) {
  const graph = {}
  const openNumbers = new Set()
  const heldNumbers = new Set()
  const notPlannedNumbers = new Set()

  // First pass: collect open numbers and special sets
  for (const t of tickets) {
    if (t.state === 'OPEN') openNumbers.add(t.number)
    const labels = new Set((t.labels || []).map((l) => l.name || l))
    if (labels.has('hold')) heldNumbers.add(t.number)
    if (t.state === 'CLOSED' && t.stateReason === 'NOT_PLANNED') notPlannedNumbers.add(t.number)
  }

  const ignored = new Set([...heldNumbers, ...notPlannedNumbers])

  // Build reverse edges
  for (const t of tickets) {
    if (!openNumbers.has(t.number)) continue
    const deps = openDependencies(t, openNumbers, ignored)
    for (const dep of deps) {
      if (!graph[dep]) graph[dep] = []
      graph[dep].push(t.number)
    }
  }

  return graph
}

// BFS to find all tickets transitively unblocked by a given ticket
export function transitiveUnblocks(number, repo, graph, tickets) {
  const visited = new Set()
  const queue = [number]
  const items = []

  while (queue.length > 0) {
    const current = queue.shift()
    if (visited.has(current)) continue
    visited.add(current)

    const dependents = graph[current] || []
    for (const dep of dependents) {
      if (!visited.has(dep)) {
        queue.push(dep)
        if (dep !== number) { // Don't include the starting node itself
          const ticket = tickets.find((t) => t.number === dep)
          if (ticket) {
            items.push({ repo: ticket.repo, number: dep, title: ticket.title })
          }
        }
      }
    }
  }

  // Remove the starting number from items if it somehow got in there
  const filtered = items.filter((i) => i.number !== number)
  filtered.sort((a, b) => a.number - b.number)

  return {
    count: filtered.length,
    items: filtered.slice(0, 3) // Top 3 only
  }
}

// Extract priority label (p0-p3) from ticket labels (array of strings)
// Matches both "priority:p0" and bare "p0" labels
function getPriority(labelNames) {
  const match = (labelNames || []).find((name) => /^(?:priority:)?(p[0-3])$/.test(name))
  if (!match) return null
  const result = match.match(/^(?:priority:)?(p[0-3])$/)
  return result ? result[1] : null
}

// A follow-up ticket filed by the hourly scan when owner decisions on a PR went unanswered (lib/owner_decisions.py,
// marvin#607). Its body carries the marker; the issue list the boards already cache is the only input, so this costs
// no GitHub call and arrives through the usual change watch.
const OWNER_DECISIONS_RE = /<!-- marvin:owner-decisions pr=(\d+) comment=(\d+) since=(\S+) question=(yes|no) -->/

export function ownerDecisionsMarker(body) {
  const m = String(body || '').match(OWNER_DECISIONS_RE)
  return m ? { pr: Number(m[1]), comment: Number(m[2]), since: m[3], question: m[4] === 'yes' } : null
}

// Waiting on MARVIN: owner decisions not acted on. Ranked above everything waiting on Gil, oldest first.
export function needsMarvinRows(tickets, { now = Date.now() } = {}) {
  const rows = []
  for (const t of tickets || []) {
    if (!t || t.state !== 'OPEN') continue
    // Only collaborators can label: the label, not the body text anyone can type, makes it a real follow-up.
    const labels = new Set((t.labels || []).map((l) => l?.name || l))
    if (!labels.has('owner-decisions') || labels.has('hold')) continue
    const mk = ownerDecisionsMarker(t.body)
    if (!mk) continue
    const since = Date.parse(mk.since)
    const hours = Number.isFinite(since) ? Math.max(0, Math.floor((now - since) / 3600_000)) : null
    const waited = hours == null ? '' : ` ${hours} h ago`
    rows.push({
      repo: t.repo,
      number: t.number,
      title: t.title,
      url: t.url,
      kind: 'needs-marvin',
      owner: 'marvin',
      question: mk.question,
      pr: { number: mk.pr, url: t.repo ? `https://github.com/${t.repo}/pull/${mk.pr}` : null },
      unblocks: { count: 0, items: [] },
      ask: mk.question
        ? `Owner asked a question on PR #${mk.pr}${waited}: no answer yet`
        : `Owner decisions on PR #${mk.pr}${waited}: not acted on yet`,
      priority: null,
      ageDays: hours == null ? 0 : Math.floor(hours / 24),
      sinceMs: Number.isFinite(since) ? since : Infinity
    })
  }
  rows.sort((a, b) => (b.question - a.question) || (a.sinceMs - b.sinceMs))
  return rows.map(({ sinceMs, ...r }) => r)
}

// Main ranking function
export function rankNeedsYou(tickets, { now = Date.now() } = {}) {
  const rows = []

  // Group by repo for block graph
  const byRepo = {}
  for (const t of tickets) {
    if (!byRepo[t.repo]) byRepo[t.repo] = []
    byRepo[t.repo].push(t)
  }

  // Build graphs per repo
  const graphs = {}
  for (const [repo, repoTickets] of Object.entries(byRepo)) {
    graphs[repo] = blocksGraph(repoTickets, repo)
  }

  // Process each ticket
  for (const t of tickets) {
    const labelNames = (t.labels || []).map((l) => l.name || l)
    const labels = new Set(labelNames)

    // Filter: must be open, have ready-for-human or needs-info label, not hold/pinned
    if (t.state !== 'OPEN') continue
    if (!labels.has('ready-for-human') && !labels.has('needs-info')) continue
    if (labels.has('hold') || labels.has('pinned')) continue

    // Calculate what we need
    const priority = getPriority(labelNames)
    const created = Date.parse(t.createdAt)
    const ageDays = Number.isFinite(created) ? Math.floor((now - created) / DAY_MS) : 0

    // Get the ask
    let ask = ''
    if (labels.has('needs-info')) {
      const missing = missingFor(t)
      ask = missing.length > 0 ? `missing: ${missing.join(', ')}` : 'waiting on info'
    } else if (labels.has('ready-for-human')) {
      const parsed = parseHumanTask(t.body)
      if (parsed.found && parsed.fields['What I need from you']) {
        ask = parsed.fields['What I need from you']
      } else if (parsed.missing.length > 0) {
        ask = `missing: ${parsed.missing.join(', ')}`
      } else {
        ask = 'needs human input'
      }
    }

    // Calculate unblocks
    const graph = graphs[t.repo] || {}
    const unblocks = transitiveUnblocks(t.number, t.repo, graph, tickets.filter((x) => x.repo === t.repo))

    rows.push({
      repo: t.repo,
      number: t.number,
      title: t.title,
      url: t.url,
      kind: labels.has('needs-info') ? 'needs-info' : 'ready-for-human',
      unblocks,
      ask,
      priority,
      ageDays
    })
  }

  // Sort: unblocks desc, priority asc (0 first), age desc (oldest first)
  rows.sort((a, b) => {
    if (a.unblocks.count !== b.unblocks.count) {
      return b.unblocks.count - a.unblocks.count
    }
    const aPri = a.priority ? parseInt(a.priority[1]) : 99
    const bPri = b.priority ? parseInt(b.priority[1]) : 99
    if (aPri !== bPri) return aPri - bPri
    return b.ageDays - a.ageDays
  })

  return [...needsMarvinRows(tickets, { now }), ...rows]
}
