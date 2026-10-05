import { existsSync, readFileSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { buildBoard } from './board.js'
import { readOverrides } from './catalog.js'
import { projectIdOf } from '../../src/lib/projects.js'
import { listTrackedTickets, readStages } from '../../webhook-server/ticket_stages.js'
import { readDispatchStatus } from './dispatch_status.js'

// Written by lib/board_registry.py (ensure_board) -- the dashboard only reads it.
export const REGISTRY_PATH = path.join(homedir(), '.claude', 'boards', 'registry.json')
const MARVIN_REPO = 'G-Eskayo/marvin'

// Due dates are decisions, so they come from the shared catalog overrides (the registry file
// itself is per-machine); an override keyed by project id wins over what the registry holds.
const projectId = (repo) => repo.split('/')[1].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

export function readRegistry(file = REGISTRY_PATH, overrides = readOverrides()) {
  if (!existsSync(file)) return []
  try {
    const data = JSON.parse(readFileSync(file, 'utf-8'))
    if (!Array.isArray(data.boards)) return []
    return data.boards.map((b) => {
      const o = overrides[projectId(b.repo)] || {}
      return { ...b, ...(o.due ? { due: o.due, dueHard: !!o.dueHard } : {}) }
    })
  } catch {
    return []
  }
}

// A board's project status (active / recent / dormant / archived) comes from the catalog, so boards of
// projects nobody is working on can sit out of the way without being deleted. Unknown = recent: never hide.
export function withProjectStatus(boards, catalog) {
  const status = Object.fromEntries((catalog?.projects || []).map((p) => [p.id, p.status]))
  return boards.map((b) => ({ ...b, status: status[projectIdOf(b.repo)] || 'recent' }))
}

// Stage events: marvin's tickets by plain number, other projects' as `<repo>-<n>` (ticket_stages.js).
export function defaultStagesFor(repo) {
  return Object.fromEntries(listTrackedTickets(undefined, repo).map((n) => [n, readStages(n, undefined, repo)]))
}

// The dispatch label says which project's ticket is running ("ticket owner/repo#7: title"; the older
// "ticket #7: title" was always marvin's), so marvin #7 is never mistaken for clarity-captions #7.
export function liveTicketNumbers(repo, task) {
  if (!task) return new Set()
  const nums = new Set()
  for (const m of task.matchAll(/(?:([\w.-]+\/[\w.-]+))?#(\d+)/g)) {
    if ((m[1] || MARVIN_REPO) === repo) nums.add(Number(m[2]))
  }
  return nums
}

export function defaultLiveNumbers(repo) {
  const live = readDispatchStatus()
  return live.busy ? liveTicketNumbers(repo, live.task) : new Set()
}

// The raw tickets and open PRs of one repo. Open tickets are fetched on their own so a long history of
// closed ones can never crowd them out (one newest-200 query silently drops the oldest open ticket);
// closed ones are the 100 most recent. PRs carry their changed files so docs they touch can be linked.
export async function fetchBoardData(repo, gh) {
  const fields = 'number,title,state,labels,body,url,createdAt,updatedAt,closedAt'
  const [openJson, closedJson, prsJson] = await Promise.all([
    gh(['issue', 'list', '--repo', repo, '--state', 'open', '--limit', '1000', '--json', fields]),
    gh(['issue', 'list', '--repo', repo, '--state', 'closed', '--limit', '100', '--json', fields]),
    gh(['pr', 'list', '--repo', repo, '--state', 'open', '--limit', '100', '--json', 'number,title,url,state,isDraft,body,files'])
  ])
  return { issues: [...JSON.parse(openJson), ...JSON.parse(closedJson)], prs: JSON.parse(prsJson) }
}

// Everything closed in this repo (up to 1000 tickets) and the merged PRs that closed them -- the
// completed-work record. No bodies or comments: this is a list, the drill-down fetches the detail.
export async function fetchCompletedData(repo, gh) {
  const [issuesJson, prsJson] = await Promise.all([
    gh(['issue', 'list', '--repo', repo, '--state', 'closed', '--limit', '1000', '--json', 'number,title,state,labels,url,createdAt,closedAt']),
    gh(['pr', 'list', '--repo', repo, '--state', 'merged', '--limit', '300', '--json', 'number,title,url,body,mergedAt'])
  ])
  return { issues: JSON.parse(issuesJson), prs: JSON.parse(prsJson) }
}

export async function loadBoard(repo, { gh, stagesFor = defaultStagesFor, liveNumbers, data } = {}) {
  try {
    const { issues, prs } = data || (await fetchBoardData(repo, gh))
    return buildBoard({
      repo,
      issues,
      prs,
      eventsByNumber: stagesFor(repo),
      liveNumbers: liveNumbers || defaultLiveNumbers(repo)
    })
  } catch (err) {
    throw new Error(`Could not load board for ${repo}: ${err.message}`)
  }
}
