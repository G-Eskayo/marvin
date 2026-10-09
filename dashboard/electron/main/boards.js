import { existsSync, readFileSync } from 'fs'
import { execFile } from 'child_process'
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

const CROSS_PROJECT_TTL_MS = 5 * 60 * 1000
const crossProjectCache = new Map()

export function clearCrossProjectCache() { crossProjectCache.clear() }

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
  const lastActivity = Object.fromEntries((catalog?.projects || []).map((p) => [p.id, p.lastActivity || null]))
  return boards.map((b) => ({ ...b, status: status[projectIdOf(b.repo)] || 'recent', lastActivity: lastActivity[projectIdOf(b.repo)] }))
}

// Stage events, keyed by project + ticket number (ticket_stages.js).
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

// Issues from other repos that are labelled for this project.
export async function fetchCrossProjectIssues(repo, registryRepos = [], gh) {
  const thisProjectId = projectIdOf(repo)
  const otherRepos = registryRepos.filter((b) => b.repo !== repo).map((b) => b.repo)

  // Skip the call entirely if there are no other registered repos.
  if (otherRepos.length === 0) return []

  // Check cache first.
  const cacheKey = `${thisProjectId}:${otherRepos.join(',')}`
  const hit = crossProjectCache.get(cacheKey)
  if (hit && Date.now() - hit.at < CROSS_PROJECT_TTL_MS) return hit.issues

  // Fetch: one search call covering all other registered repos with this project's label. `gh search issues`
  // supports fewer fields than `gh issue list` (no stateReason) and returns 30 by default.
  const fields = 'number,title,state,labels,body,url,createdAt,updatedAt,closedAt,repository'
  const args = [
    'search',
    'issues',
    '--label', `project:${thisProjectId}`,
    '--limit', '300',
    '--json', fields
  ]
  for (const r of otherRepos) args.push('--repo', r)

  let json
  try {
    json = await gh(args)
  } catch (e) {
    // The project's own tickets still show; this part retries on the next load (not cached).
    console.error(`[boards] cross-project tickets for ${repo} unavailable: ${String(e.message || e).slice(0, 200)}`)
    return []
  }
  const issues = JSON.parse(json).map((issue) => ({
    ...issue,
    state: issue.state.toUpperCase(),
    repo: issue.repository.nameWithOwner
  }))

  // Cache the result.
  crossProjectCache.set(cacheKey, { at: Date.now(), issues })
  return issues
}

// The raw tickets and open PRs of one repo. Open tickets are fetched on their own so a long history of
// closed ones can never crowd them out (one newest-200 query silently drops the oldest open ticket);
// closed ones are the 100 most recent. PRs carry their changed files so docs they touch can be linked.
export async function fetchBoardData(repo, gh) {
  const fields = 'number,title,state,stateReason,labels,body,url,createdAt,updatedAt,closedAt'
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

// Does work already exist for each open ticket? Asked of lib/ticket_evidence.py (git + PRs), cached for
// a few minutes because it fetches. Any failure means "no evidence", never a broken board.
const EVIDENCE_TTL_MS = 5 * 60 * 1000
const evidenceCache = new Map()
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const EVIDENCE_CLI = path.join(homedir(), '.agents', 'lib', 'ticket_evidence.py')

export function getEvidence(repo, { run = defaultEvidenceRun, now = Date.now() } = {}) {
  const hit = evidenceCache.get(repo)
  if (hit && now - hit.at < EVIDENCE_TTL_MS) return hit.promise
  const promise = run(repo).then((out) => JSON.parse(out)).catch(() => ({}))
  evidenceCache.set(repo, { at: now, promise })
  return promise
}

function defaultEvidenceRun(repo) {
  return new Promise((resolve, reject) =>
    execFile(PY, [EVIDENCE_CLI, 'report', repo], { timeout: 90000 }, (err, stdout) => (err ? reject(err) : resolve(stdout)))
  )
}

export function clearEvidenceCache() { evidenceCache.clear() }

export async function loadBoard(repo, { gh, registryRepos = [], stagesFor = defaultStagesFor, liveNumbers, data, evidence = {} } = {}) {
  try {
    const { issues: ownIssues, prs } = data || (await fetchBoardData(repo, gh))
    const thisProjectId = projectIdOf(repo)

    // Partition own issues: separate those with project:<x> labels where x is not this repo.
    const otherProjectsCount = new Map()
    const ownIssuesList = ownIssues.filter((issue) => {
      const labels = (issue.labels || []).map((l) => l.name)
      for (const label of labels) {
        if (label.startsWith('project:')) {
          const foreignProjectId = label.slice('project:'.length)
          if (foreignProjectId !== thisProjectId) {
            otherProjectsCount.set(foreignProjectId, (otherProjectsCount.get(foreignProjectId) || 0) + 1)
            return false
          }
        }
      }
      return true
    })

    // Build the board for own repo only.
    const ownBoard = buildBoard({
      repo,
      issues: ownIssuesList,
      prs,
      eventsByNumber: stagesFor(repo),
      liveNumbers: liveNumbers || defaultLiveNumbers(repo),
      evidenceByNumber: evidence
    })

    // Fetch and merge cross-project issues.
    const crossProjectIssues = await fetchCrossProjectIssues(repo, registryRepos, gh)

    // Group cross-project issues by their origin repo.
    const issuesByForeignRepo = new Map()
    for (const issue of crossProjectIssues) {
      const foreignRepo = issue.repo
      if (!issuesByForeignRepo.has(foreignRepo)) {
        issuesByForeignRepo.set(foreignRepo, [])
      }
      issuesByForeignRepo.get(foreignRepo).push(issue)
    }

    // Build a board for each foreign repo's issues.
    const foreignBoards = []
    for (const [foreignRepo, foreignIssues] of issuesByForeignRepo) {
      const foreignBoard = buildBoard({
        repo: foreignRepo,
        issues: foreignIssues,
        prs: []
      })
      foreignBoards.push({ repo: foreignRepo, board: foreignBoard })
    }

    // Merge columns: for each column, concatenate own and foreign cards (tagging foreign with repo),
    // then sort using the same order as buildBoard (oldest-first for open, newest-first for done/archive).
    const mergedColumns = ownBoard.columns.map((ownCol) => {
      const merged = { ...ownCol, cards: [...ownCol.cards] }
      for (const { repo: foreignRepo, board: foreignBoard } of foreignBoards) {
        const foreignCol = foreignBoard.columns.find((c) => c.id === ownCol.id)
        if (foreignCol) {
          for (const card of foreignCol.cards) {
            merged.cards.push({ ...card, repo: foreignRepo })
          }
        }
      }
      // Re-sort after merging: oldest-first for open columns, newest-first for done.
      const newestFirst = (a, b) => (b.closedAt || '').localeCompare(a.closedAt || '')
      merged.cards.sort(merged.id === 'done' ? newestFirst : (a, b) => a.createdAt.localeCompare(b.createdAt))
      return merged
    })

    // Merge archives.
    const doneCol = mergedColumns.find((c) => c.id === 'done')
    if (doneCol) {
      doneCol.archive = [...(doneCol.archive || [])]
      for (const { repo: foreignRepo, board: foreignBoard } of foreignBoards) {
        const foreignDone = foreignBoard.columns.find((c) => c.id === 'done')
        if (foreignDone?.archive) {
          for (const card of foreignDone.archive) {
            doneCol.archive.push({ ...card, repo: foreignRepo })
          }
        }
      }
      const newestFirst = (a, b) => (b.closedAt || '').localeCompare(a.closedAt || '')
      doneCol.archive.sort(newestFirst)
    }

    // Build otherProjects array: resolve each foreign project id to a board name if registered.
    const otherProjects = Array.from(otherProjectsCount.entries()).map(([projectId, count]) => {
      const board = registryRepos.find((b) => projectIdOf(b.repo) === projectId)
      return {
        projectId,
        count,
        repo: board?.repo || null,
        name: board?.name || null
      }
    })

    const fetchedAt = new Date().toISOString()
    return {
      repo,
      columns: mergedColumns,
      otherProjects,
      fetchedAt
    }
  } catch (err) {
    throw new Error(`Could not load board for ${repo}: ${err.message}`)
  }
}
