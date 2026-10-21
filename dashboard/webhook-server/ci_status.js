import { MergeFailure, refusal } from './failure.js'

const FAILED = new Set(['FAILURE', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE'])

// What GitHub says about a PR's checks (`gh pr view --json statusCheckRollup`): none / passing / pending / failing.
// Handles both kinds of entry: Actions check runs and the older commit statuses.
export function ciState(rollup) {
  const failing = []
  const pending = []
  for (const c of rollup || []) {
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
  const state = !(rollup || []).length ? 'none' : failing.length ? 'failing' : pending.length ? 'pending' : 'passing'
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
export async function assertChecksGreen(prUrl, exec) {
  let rollup
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'statusCheckRollup'])
    rollup = JSON.parse(stdout).statusCheckRollup
  } catch {
    return
  }
  const { state, failing, pending } = ciState(rollup)
  if (state === 'failing') {
    throw new MergeFailure(refusal('CI_FAILED', 'request', `GitHub's checks failed on this PR: ${failing.join(', ')}`,
      'Fix what the failing checks report. The PR is sent back for rework.', 'reengage'))
  }
  if (state === 'pending') {
    throw new MergeFailure(refusal('CI_PENDING', 'request', `GitHub's checks are still running: ${pending.join(', ')}`,
      'Wait for them to finish, then approve again. The PR was not sent back.'))
  }
}
