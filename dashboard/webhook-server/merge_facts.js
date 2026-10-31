import { readFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { fileURLToPath } from 'url'
import { enrichForOrder, mainStateFrom } from './merge_order.js'
import { readRebaseStatus } from './rebase_status.js'

// What the merge queue reads to decide (marvin#231), all from what MARVIN already records; nothing new is measured:
//   - the repo's open PRs and open tickets (two gh calls per decision, only for a repo with something queued)
//   - answered-but-unbuilt Decisions: lib/owner_decisions.py `waiting --json` (one GraphQL call for every repo),
//     kept here and refreshed on triggers, single flight
//   - main's health: CI's main-red ticket (lib/main_red.py) and ~/.claude/logs/main-health.json (lib/main_health.py)
//   - conflict repairs that failed on a commit: ~/.claude/logs/conflict-repair.json (lib/conflict_repair.py)
//   - the post-merge conflict check (#225): pr-rebase-status.json
// Paths are worked out from os.homedir() at call time, so tests with a temp HOME never touch the real logs.

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..', '..')
const OWNER_DECISIONS = path.join(ROOT, 'lib', 'owner_decisions.py')
const PROFILE_SCRIPT = path.join(ROOT, 'lib', 'project_profile.py')
const VENV_PYTHON = path.join(ROOT, 'venv', 'bin', 'python')
const MARVIN = 'G-Eskayo/marvin'

const logs = () => path.join(os.homedir(), '.claude', 'logs')
const readJson = (file, fallback) => { try { return JSON.parse(readFileSync(file, 'utf-8')) } catch { return fallback } }
export const readMainHealth = () => readJson(path.join(logs(), 'main-health.json'), null)
export const readRepairFailures = () => {
  const all = readJson(path.join(logs(), 'conflict-repair.json'), {})
  const out = {}
  for (const [k, v] of Object.entries(all && typeof all === 'object' ? all : {})) if (v?.failed_sha) out[k] = v.failed_sha
  return out
}

// owner_decisions.py rows that are MARVIN's move: the owner answered, nothing replied, and no work commit came after.
export function unbuiltFrom(rows) {
  return (Array.isArray(rows) ? rows : []).filter((r) => r && r.url && !r.addressed_by && !r.built_since).map((r) => r.url)
}

// The answered-but-unbuilt PRs, refreshed when asked (a trigger), one refresh at a time; a refresh asked for while one
// runs is run once more after it. GitHub unreadable: the last answer is kept (never "nothing unbuilt" on a failure).
export function createUnbuiltCache({ exec, python = VENV_PYTHON, script = OWNER_DECISIONS, log = () => {} }) {
  let urls = new Set()
  let at = null
  let inflight = null
  let dirty = false
  async function once() {
    try {
      const { stdout } = await exec(python, [script, 'waiting', '--json'], { timeout: 90_000 })
      urls = new Set(unbuiltFrom(JSON.parse(String(stdout || '[]'))))
      at = Date.now()
    } catch (e) {
      log(`[merge-queue] could not read owner decisions: ${String(e?.message || e).slice(0, 200)}`)
    }
  }
  function refresh() {
    if (inflight) { dirty = true; return inflight }
    inflight = (async () => {
      do { dirty = false; await once() } while (dirty)
    })().finally(() => { inflight = null })
    return inflight
  }
  return { refresh, get: () => urls, at: () => at, ready: () => at !== null }
}

// The open tickets that say main is red, or fix it (main-red, incident, bug+p0 "Main red"), for every repo of these
// owners, by repo: what MR Review needs for "main is red" on a Mac whose boards aren't loaded. Two search calls per
// refresh (a trigger), single flight; a failed read keeps the last answer.
const FIX_QUERIES = (owners) => {
  const who = owners.map((o) => `user:${o}`).join(' ')
  return [`is:issue is:open ${who} label:main-red,incident`, `is:issue is:open ${who} label:bug label:priority:p0 in:title "main red"`]
}
export function ticketsByRepo(searchResults) {
  const out = {}
  for (const item of searchResults || []) {
    const repo = String(item?.repository_url || '').match(/repos\/([^/]+\/[^/]+)$/)?.[1]
    if (!repo || !Number.isFinite(item.number)) continue
    const list = (out[repo] ||= [])
    if (!list.some((i) => i.number === item.number)) list.push({ number: item.number, title: item.title || '', state: 'OPEN', labels: (item.labels || []).map((l) => l?.name).filter(Boolean) })
  }
  return out
}
export function createFixTicketsCache({ exec, owners = () => ['G-Eskayo'], log = () => {} }) {
  let byRepo = {}
  let inflight = null
  let dirty = false
  async function once() {
    try {
      const results = []
      for (const q of FIX_QUERIES(owners())) {
        const { stdout } = await exec('gh', ['api', '-X', 'GET', 'search/issues', '-f', `q=${q}`, '-f', 'per_page=100'], { timeout: 30_000 })
        results.push(...(JSON.parse(String(stdout || '{}')).items || []))
      }
      byRepo = ticketsByRepo(results)
    } catch (e) {
      log(`[merge-queue] could not read main-red tickets: ${String(e?.message || e).slice(0, 200)}`)
    }
  }
  function refresh() {
    if (inflight) { dirty = true; return inflight }
    inflight = (async () => { do { dirty = false; await once() } while (dirty) })().finally(() => { inflight = null })
    return inflight
  }
  return { refresh, get: () => byRepo }
}

// The base branch of a repo: marvin's is main; another project's comes from its profile (asked once).
export function createBaseLookup({ exec, python = VENV_PYTHON, script = PROFILE_SCRIPT }) {
  const known = new Map([[MARVIN, 'main']])
  return async (repo) => {
    if (known.has(repo)) return known.get(repo)
    let base = 'main'
    try { base = JSON.parse((await exec(python, [script, 'gate-info', repo], { timeout: 30_000 })).stdout).base_branch || 'main' } catch { /* main */ }
    known.set(repo, base)
    return base
  }
}

const PR_FIELDS = 'number,title,url,body,baseRefName,headRefName,headRefOid,mergeable,statusCheckRollup,isDraft,isCrossRepository'

// load(repo) for the queue runner: { openPrs (enriched), mainState }. Throws when GitHub can't be read: the runner
// then decides nothing (a queue never merges on a guess).
export function createQueueLoader({ exec, unbuilt, baseOf, health = readMainHealth, repairs = readRepairFailures, rebase = readRebaseStatus }) {
  return async (repo) => {
    const [prsOut, issuesOut] = await Promise.all([
      exec('gh', ['pr', 'list', '--repo', repo, '--state', 'open', '--limit', '100', '--json', PR_FIELDS]),
      exec('gh', ['issue', 'list', '--repo', repo, '--state', 'open', '--limit', '500', '--json', 'number,title,labels'])
    ])
    const prs = JSON.parse(String(prsOut?.stdout || ''))
    const issues = JSON.parse(String(issuesOut?.stdout || ''))
    if (!Array.isArray(prs) || !Array.isArray(issues)) throw new Error('GitHub did not answer with lists')
    const base = await baseOf(repo)
    return {
      openPrs: enrichForOrder(prs.filter((p) => !p.isCrossRepository).map((p) => ({ ...p, repo })), { repo, issues, unbuilt: unbuilt(), repairFailed: repairs(), rebaseStatus: rebase() }),
      mainState: mainStateFrom({ issues, health: repo === MARVIN ? health() : null, base })
    }
  }
}

// The owner's Approve of a PR whose answers aren't built yet asks for the work now, not after the scan's grace hours
// (lib/owner_decisions.py `request`: files the one follow-up ticket, or says it is already filed). Once per PR per run.
export function createFollowUpRequester({ exec, python = VENV_PYTHON, script = OWNER_DECISIONS, log = () => {} }) {
  const asked = new Set()
  return (repo, number) => {
    const key = `${repo}#${number}`
    if (asked.has(key)) return Promise.resolve(false)
    asked.add(key)
    return exec(python, [script, 'request', '--repo', repo, '--pr', String(number)], { timeout: 90_000 })
      .then(({ stdout }) => { log(`[merge-queue] ${key}: answers not built yet; follow-up: ${String(stdout || '').trim().slice(0, 200)}`); return true })
      .catch((e) => { asked.delete(key); log(`[merge-queue] ${key}: could not request the follow-up: ${String(e?.message || e).slice(0, 200)}`); return false })
  }
}
