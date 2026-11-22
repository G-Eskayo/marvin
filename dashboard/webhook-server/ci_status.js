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

// Default poll and timeout durations for waitForRequiredChecks. Injected via opts for testing.
export const CHECKS_POLL_MS = 10_000
export const CHECKS_WAIT_TIMEOUT_MS = 20 * 60 * 1000

// Wait for required checks (not gate checks) to pass on a PR. Used when the gate needs them.
// Polls GitHub's status repeatedly and returns once all pass or time runs out.
// opts.names: check names to wait for (required checks the PR has). If the PR has a check not in this list, it passes when the required ones pass.
// opts.timeoutMs: how long to wait before giving up. Default CHECKS_WAIT_TIMEOUT_MS.
// opts.pollMs: how long between checks. Default CHECKS_POLL_MS.
// Throws MergeFailure with CI_TIMEOUT if time expires, or CI_SUPERSEDED if the PR is superseded mid-wait.
export async function waitForRequiredChecks(prUrl, exec, names = [], { timeoutMs = CHECKS_WAIT_TIMEOUT_MS, pollMs = CHECKS_POLL_MS } = {}) {
  if (!names.length) return
  const start = Date.now()
  let priorHeadRefOid = null
  for (;;) {
    let rollup, headRefOid
    try {
      const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'statusCheckRollup,headRefOid,state'])
      const json = JSON.parse(stdout)
      if (json.state && json.state !== 'OPEN') {
        throw new MergeFailure(refusal('CI_SUPERSEDED', 'gate', 'The PR is no longer open (closed, merged, or draft). It was superseded.',
          'The PR no longer exists; nothing to merge.', 'escalate'))
      }
      headRefOid = json.headRefOid
      if (priorHeadRefOid !== null && headRefOid !== priorHeadRefOid) {
        throw new MergeFailure(refusal('CI_SUPERSEDED', 'gate', 'The PR was pushed while the check watched it. It was superseded.',
          'The commit changed; run the merge gate again to test the new code.', 'escalate'))
      }
      priorHeadRefOid = headRefOid
      rollup = json.statusCheckRollup
    } catch (e) {
      if (e instanceof MergeFailure) throw e
      const elapsed = Date.now() - start
      if (elapsed > timeoutMs) {
        throw new MergeFailure(refusal('CI_TIMEOUT', 'gate', `GitHub's checks were still running after ${Math.round(elapsed / 60000)} min`,
          'The PR was not sent back. Approve again after checking the status on GitHub.', 'escalate'))
      }
      await new Promise((resolve) => setTimeout(resolve, pollMs))
      continue
    }
    // Track which required names have appeared; names that never appear are treated as pending.
    const seenNames = new Set((rollup || []).map((c) => c.name || c.context))
    const missingNames = names.filter((n) => !seenNames.has(n))
    const pending = [...(missingNames.length ? missingNames : [])]
    // For checks that have appeared, determine their state.
    const namedState = ciState(rollup, { ignore: (rollup || []).map((c) => c.name || c.context).filter((n) => !names.includes(n)) })
    if (namedState.state === 'failing') {
      throw new MergeFailure(refusal('CI_FAILED', 'gate', `GitHub's checks failed on this PR: ${namedState.failing.join(', ')}`,
        'Fix what the failing checks report. The PR is sent back for rework.', 'reengage'))
    }
    // All required checks have appeared and are passing.
    if (namedState.state === 'passing' && !missingNames.length) return
    const elapsed = Date.now() - start
    if (elapsed > timeoutMs) {
      const stillPending = [...new Set([...pending, ...namedState.pending])].sort()
      throw new MergeFailure(refusal('CI_TIMEOUT', 'gate', `GitHub's checks were still running after ${Math.round(elapsed / 60000)} min: ${stillPending.join(', ')}`,
        'The PR was not sent back. Approve again after checking the status on GitHub.', 'escalate'))
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs))
  }
}
