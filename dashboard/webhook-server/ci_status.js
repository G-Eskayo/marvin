import { readFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { MergeFailure, refusal } from './failure.js'

const FAILED = new Set(['FAILURE', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE'])

export const REQUIRED_CHECKS_TIMEOUT_MS = 70 * 60_000  // 70 minutes; worst case in #1100 is ~65 min
export const REQUIRED_CHECKS_POLL_MS = 15_000

// What GitHub says about a PR's checks (`gh pr view --json statusCheckRollup`): none / passing / pending / failing.
// Handles both kinds of entry: Actions check runs and the older commit statuses.
// ignore (marvin#1099): names of checks the merge gate runs itself (gateChecks). GitHub's copy of those doesn't count:
// the gate runs them again on the commit it merges, so a cancelled or failed GitHub run of one never holds a PR.
// only: an allow-list of check names (a name not in `only` is treated as not present), additive and backward-compatible.
export function ciState(rollup, { ignore = null, only = null } = {}) {
  const failing = []
  const pending = []
  const skip = new Set(Array.isArray(ignore) ? ignore : [])
  const allowList = only ? new Set(Array.isArray(only) ? only : []) : null
  const counted = (rollup || []).filter((c) => {
    const name = c?.__typename === 'StatusContext' ? c.context : c?.name
    return !skip.has(name) && (!allowList || allowList.has(name))
  })
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

// Every check name in the repo's .github/required-checks.json, with no filtering (ci-only or otherwise).
// Unreadable or broken: [].
export function requiredCheckNames(dir = path.join(os.homedir(), '.agents')) {
  try {
    const checks = JSON.parse(readFileSync(path.join(dir, '.github', 'required-checks.json'), 'utf8')).checks
    return Array.isArray(checks) ? checks.filter((c) => c && typeof c.name === 'string').map((c) => c.name) : []
  } catch {
    return []
  }
}

// Fetch the current head commit SHA of a PR (40-char hex SHA-1). Best effort: empty string on failure.
export async function currentHeadSha(prUrl, exec) {
  try {
    const sha = String((await exec('gh', ['pr', 'view', prUrl, '--json', 'headRefOid', '--jq', '.headRefOid']))?.stdout || '').trim()
    return /^[0-9a-f]{40}$/.test(sha) ? sha : ''
  } catch {
    return ''
  }
}

// After the gate's checks pass, say so on the commit it merges, so GitHub shows what was really checked. Best effort:
// a refused or failed post never blocks the merge. When sha is provided, skips its own fetch (backward compatible).
export async function postGateStatus(prUrl, exec, names = [], sha = null) {
  try {
    const m = /^https:\/\/github\.com\/([^/]+\/[^/]+)\/pull\/\d+/.exec(String(prUrl))
    if (!m) return false
    const commitSha = sha || (await currentHeadSha(prUrl, exec))
    if (!commitSha) return false
    const what = names.length ? names.join(', ') : 'the required checks'
    await exec('gh', ['api', `repos/${m[1]}/statuses/${commitSha}`, '-f', 'state=success', '-f', 'context=MARVIN gate',
      '-f', `description=${`Passed on the rebased commit: ${what}`.slice(0, 140)}`])
    return true
  } catch {
    return false
  }
}

// Poll GitHub until all required checks finish or the deadline passes. Throws CI_FAILED if any fail before they all
// pass or are absent; CI_TIMEOUT or HEAD_MOVED if the deadline expires or the head SHA moves. The head SHA at start
// is the one being waited for; a move means the PR was pushed again (the caller should retry and wait again).
//
// opts (all optional):
//   sha: the commit SHA to wait for (defaults to current head; a move from this SHA triggers HEAD_MOVED).
//   names: required check names (defaults to []; ciState only checks these, so an empty list means pass immediately).
//   timeoutMs: deadline in ms from now (defaults to REQUIRED_CHECKS_TIMEOUT_MS).
//   pollMs: polling interval in ms (defaults to REQUIRED_CHECKS_POLL_MS).
//   sleep: sleep function (defaults to setTimeout); tested with a mock.
//   now: current time function (defaults to Date.now); for testing.
export async function waitForRequiredChecks(prUrl, exec, { sha = null, names = [], timeoutMs = REQUIRED_CHECKS_TIMEOUT_MS, pollMs = REQUIRED_CHECKS_POLL_MS, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), now = Date.now } = {}) {
  const deadline = now() + timeoutMs
  let currentSha = sha || (await currentHeadSha(prUrl, exec))
  if (!currentSha) {
    throw new MergeFailure(refusal('HEAD_MOVED', 'gate', 'Could not read the PR head SHA at the start of the check wait',
      'Approve again once GitHub settles. The PR was not sent back.', 'retry'))
  }
  const checkNames = new Set(Array.isArray(names) ? names : [])
  for (;;) {
    const remaining = deadline - now()
    if (remaining <= 0) {
      throw new MergeFailure(refusal('CI_TIMEOUT', 'gate', `Required checks did not finish within ${Math.max(1, Math.round(timeoutMs / 60000))} min`,
        'Approve again when they finish, or extend the deadline. The PR was not sent back.', 'retry'))
    }
    try {
      const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'headRefOid,statusCheckRollup'])
      const data = JSON.parse(stdout)
      if (data.headRefOid !== currentSha) {
        throw new MergeFailure(refusal('HEAD_MOVED', 'gate', `The PR head moved from ${currentSha.slice(0, 8)} to ${data.headRefOid.slice(0, 8)} while waiting for checks`,
          'Approve again once GitHub settles. The PR was not sent back.', 'retry'))
      }
      const { state, failing } = ciState(data.statusCheckRollup, { only: Array.from(checkNames) })
      if (failing.length) {
        throw new MergeFailure(refusal('CI_FAILED', 'gate', `GitHub's checks failed on this PR: ${failing.join(', ')}`,
          'Fix what the failing checks report. The PR is sent back for rework.', 'reengage'))
      }
      if (state === 'passing' || state === 'none') return
    } catch (e) {
      if (e instanceof MergeFailure) throw e
      const text = String(e?.message || e).toLowerCase()
      if (text.includes('not found') || text.includes('could not resolve')) {
        throw new MergeFailure(refusal('HEAD_MOVED', 'gate', 'GitHub has no such PR anymore or it lost the head ref',
          'Approve again once GitHub settles. The PR was not sent back.', 'retry'))
      }
    }
    await sleep(pollMs)
  }
}
