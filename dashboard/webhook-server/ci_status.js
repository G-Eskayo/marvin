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
