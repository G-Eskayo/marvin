import { existsSync, readFileSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { buildBoard } from './board.js'
import { listTrackedTickets, readStages } from '../../webhook-server/ticket_stages.js'
import { readDispatchStatus } from './dispatch_status.js'

// Written by lib/board_registry.py (ensure_board) -- the dashboard only reads it.
export const REGISTRY_PATH = path.join(homedir(), '.claude', 'boards', 'registry.json')
const MARVIN_REPO = 'G-Eskayo/marvin'

export function readRegistry(file = REGISTRY_PATH) {
  if (!existsSync(file)) return []
  try {
    const data = JSON.parse(readFileSync(file, 'utf-8'))
    return Array.isArray(data.boards) ? data.boards : []
  } catch {
    return []
  }
}

// Stage events are keyed by ticket number only, so they belong to the MARVIN
// repo alone until stage keys carry a repo (CONTEXT.md "Project boards").
function defaultStagesFor(repo) {
  if (repo !== MARVIN_REPO) return {}
  return Object.fromEntries(listTrackedTickets().map((n) => [n, readStages(n)]))
}

function defaultLiveNumbers(repo) {
  if (repo !== MARVIN_REPO) return new Set()
  const live = readDispatchStatus()
  const m = live.busy && live.task ? [...live.task.matchAll(/#(\d+)/g)] : []
  return new Set(m.map((x) => Number(x[1])))
}

export async function loadBoard(repo, { gh, stagesFor = defaultStagesFor, liveNumbers } = {}) {
  try {
    const [issuesJson, prsJson] = await Promise.all([
      gh(['issue', 'list', '--repo', repo, '--state', 'all', '--limit', '200', '--json', 'number,title,state,labels,body,url,createdAt']),
      gh(['pr', 'list', '--repo', repo, '--state', 'open', '--limit', '100', '--json', 'number,title,url,state,isDraft,body'])
    ])
    return buildBoard({
      repo,
      issues: JSON.parse(issuesJson),
      prs: JSON.parse(prsJson),
      eventsByNumber: stagesFor(repo),
      liveNumbers: liveNumbers || defaultLiveNumbers(repo)
    })
  } catch (err) {
    throw new Error(`Could not load board for ${repo}: ${err.message}`)
  }
}
