import { readFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { MergeFailure, refusal } from './failure.js'

const FAILED = new Set(['FAILURE', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE'])

// What GitHub says about a PR's checks (`gh pr view --json statusCheckRollup`): none / passing / pending / failing.
// Handles both kinds of entry: Actions check runs and the older commit statuses.
// ignore (marvin#1099): names of checks the merge gate runs itself (gateChecks). GitHub's copy of those doesn't count:
// the gate runs them again on the commit it merges, so a cancelled or failed GitHub run of one never holds a PR.
export function ciState(rollup, { ignore = null } = {}) {
  const failing = []
  const pending = []
  const skip = new Set(Array.isArray(ignore) ? ignore : [])
  const counted = (rollup || []).filter((c) => !skip.has(c?.__typename === 'StatusContext' ? c.context : c?.name))
  for (const c of counted) {
    if (c.__typename === 'StatusContext') {
      const name = c.context || 'status'
      if (c.state === 'FAILURE' || c.state === 'ERROR') failing.push(name)
      else if (c.state === 'PENDING' || c.state === 'EXPECTED') pending.push(name)
    } else {
      const name = c.name || 'check'
      if (c.status !== 'COMPLETED') pending.push(name)
      else if (FAILED.has(c.conclusion)) failing.push(name)
    }
  }
  const state = !counted.length ? 'none' : failing.length ? 'failing' : pending.length ? 'pending' : 'passing'
  return { state, failing, pending }
}

// One row per check, for MR Review's progress bar and drill-down (marvin#555): its name, a plain state
// (passed / failed / skipped / neutral / running / queued), whether it finished, and GitHub's own start and finish
// times (strings, untouched; a commit status has only when it was posted, and no finish time). ciState above is what
// the merge gate decides on and is unchanged by this.
const RUN_STATE = { SUCCESS: 'passed', SKIPPED: 'skipped', NEUTRAL: 'neutral', STALE: 'neutral' }
function checkRow(c) {
  if (c.__typename === 'StatusContext') {
    const s = String(c.state || '').toUpperCase()
    const status = s === 'SUCCESS' ? 'passed' : s === 'FAILURE' || s === 'ERROR' ? 'failed' : s === 'PENDING' ? 'running' : 'queued'
    return { key: `status|${c.context}`, name: c.context || 'status', status, done: status === 'passed' || status === 'failed', startedAt: c.startedAt || c.createdAt || null, completedAt: null }
  }
  const st = String(c.status || '').toUpperCase()
  const concl = String(c.conclusion || '').toUpperCase()
  const done = st === 'COMPLETED'
  const status = done ? (FAILED.has(concl) ? 'failed' : RUN_STATE[concl] || 'neutral') : st === 'IN_PROGRESS' ? 'running' : 'queued'
  return { key: `run|${c.workflowName || ''}|${c.name}`, name: c.name || 'check', status, done, startedAt: c.startedAt || null, completedAt: c.completedAt || null }
}

// A re-run leaves the old run beside the new one: the newer wins. Newer = later start; a run not started yet (no start
// time) that is still pending is newer than a finished one.
function newer(a, b) {
  const ta = Date.parse(a.startedAt)
  const tb = Date.parse(b.startedAt)
  if (Number.isFinite(ta) && Number.isFinite(tb)) return tb >= ta ? b : a
  if (a.done !== b.done) return a.done ? b : a
  return b
}

export function checkRuns(rollup) {
  if (!Array.isArray(rollup)) return []
  const byKey = new Map()
  for (const c of rollup) {
    if (!c || typeof c !== 'object') continue
    const row = checkRow(c)
    byKey.set(row.key, byKey.has(row.key) ? newer(byKey.get(row.key), row) : row)
  }
  return [...byKey.values()].map(({ key, ...row }) => row)
}

// Merging waits for the repo's own CI when it has one. Failing checks mean the code is wrong, so the PR goes back
// for rework with the check names; running checks are only a reason to wait (the PR is not sent back). A repo
// with no CI is unaffected, and a metadata hiccup does not block (the merge gate still retests locally).
// ignore: the checks the gate itself runs (marvin#1099); only GitHub-only checks (the secret scan) are waited for.
export async function assertChecksGreen(prUrl, exec, { ignore = null } = {}) {
  let rollup
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'statusCheckRollup'])
    rollup = JSON.parse(stdout).statusCheckRollup
  } catch {
    return
  }
  const { state, failing, pending } = ciState(rollup, { ignore })
  if (state === 'failing') {
    throw new MergeFailure(refusal('CI_FAILED', 'request', `GitHub's checks failed on this PR: ${failing.join(', ')}`,
      'Fix what the failing checks report. The PR is sent back for rework.', 'reengage'))
  }
  if (state === 'pending') {
    throw new MergeFailure(refusal('CI_PENDING', 'request', `GitHub's checks are still running: ${pending.join(', ')}`,
      'Wait for them to finish, then approve again. The PR was not sent back.'))
  }
}

// marvin#1099: the names of the checks the merge gate runs itself, from a checkout's .github/required-checks.json
// (the gate's own list: every check not marked CI-only). GitHub's copy of these never holds a PR. Unreadable or broken:
// [] (nothing is ignored; the gate itself refuses a broken list when it runs).
export function gateCheckNames(dir = path.join(os.homedir(), '.agents')) {
  try {
    const checks = JSON.parse(readFileSync(path.join(dir, '.github', 'required-checks.json'), 'utf8')).checks
    return Array.isArray(checks) ? checks.filter((c) => c && (c.where || 'both') === 'both' && typeof c.name === 'string').map((c) => c.name) : []
  } catch {
    return []
  }
}

// After the gate's checks pass, say so on the commit it merges, so GitHub shows what was really checked. Best effort:
// a refused or failed post never blocks the merge.
export async function postGateStatus(prUrl, exec, names = []) {
  try {
    const m = /^https:\/\/github\.com\/([^/]+\/[^/]+)\/pull\/\d+/.exec(String(prUrl))
    if (!m) return false
    const sha = String((await exec('gh', ['pr', 'view', prUrl, '--json', 'headRefOid', '--jq', '.headRefOid']))?.stdout || '').trim()
    if (!/^[0-9a-f]{40}$/.test(sha)) return false
    const what = names.length ? names.join(', ') : 'the required checks'
    await exec('gh', ['api', `repos/${m[1]}/statuses/${sha}`, '-f', 'state=success', '-f', 'context=MARVIN gate',
      '-f', `description=${`Passed on the rebased commit: ${what}`.slice(0, 140)}`])
    return true
  } catch {
    return false
  }
}
