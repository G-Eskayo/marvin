import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs'
import path from 'path'
import os from 'os'

// Record of rerun attempts for no-runner checks, keyed by PR url. {url, pr, number, sha, runId, reason, at}.
// rerun state: 'started' (attempt in flight), 'already-tried' (tried before, failed), 'refused' (should not retry).
// Lives on the machine running the webhook; the dashboard reads it through the main merge queue endpoint
// or posts to /no-runner-rerun to trigger a rerun.
export const NO_RUNNER_RERUN_PATH = path.join(os.homedir(), '.claude', 'logs', 'no-runner-rerun.json')
const KEEP_MS = 7 * 24 * 3600 * 1000

export function readNoRunnerReruns(file = NO_RUNNER_RERUN_PATH) {
  if (!existsSync(file)) return {}
  try {
    return JSON.parse(readFileSync(file, 'utf-8'))
  } catch {
    return {}
  }
}

export function recordNoRunnerRerun(entries, file = NO_RUNNER_RERUN_PATH, now = () => new Date()) {
  const horizon = now().getTime() - KEEP_MS
  const all = { ...readNoRunnerReruns(file) }
  for (const e of entries) {
    const key = e.key || e.url // prefer explicit key, fall back to URL for backwards compat
    all[key] = e
  }
  const kept = Object.fromEntries(Object.entries(all).filter(([, e]) => Date.parse(e.at) >= horizon))
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, JSON.stringify(kept, null, 2))
}

// Attempt to trigger a rerun of a no-runner check. The check is re-run on GitHub,
// and once it completes, the merge will be retried. Never throws.
export async function triggerNoRunnerRerun({ repo, number, sha, runId, checkName, exec, file = NO_RUNNER_RERUN_PATH }) {
  if (!repo || !number || !sha || !runId || !exec) return { ok: false, reason: 'missing arguments' }

  const recordKey = `${repo}#${number}@${sha}:${checkName}`

  try {
    // Check if we already tried to rerun this check at this commit
    const existing = readNoRunnerReruns(file)
    if (existing[recordKey]?.rerun === 'started') {
      return { ok: true, rerun: 'already-tried', reason: 'rerun already started' }
    }
    if (existing[recordKey]?.rerun === 'already-tried') {
      return { ok: false, rerun: 'refused', reason: 'rerun already failed once' }
    }

    // GitHub doesn't have a direct API to rerun a specific check; we rerun the entire workflow run.
    // This is the only public way to retry a check on GitHub. The run will restart with the same commit.
    await exec('gh', ['api', `repos/${repo}/actions/runs/${runId}/rerun`, '-X', 'POST'])

    const now = new Date()
    recordNoRunnerRerun([{
      key: recordKey,
      url: `https://github.com/${repo}/pull/${number}`,
      pr: number,
      repo,
      sha,
      runId,
      checkName,
      reason: 'no-runner check, triggered rerun',
      rerun: 'started',
      at: now.toISOString()
    }], file, () => now)

    return { ok: true, rerun: 'started' }
  } catch (err) {
    // Record the failure so we don't retry the same check at the same commit immediately
    const now = new Date()
    recordNoRunnerRerun([{
      key: recordKey,
      url: `https://github.com/${repo}/pull/${number}`,
      pr: number,
      repo,
      sha,
      runId,
      checkName,
      reason: `rerun failed: ${String(err?.message || err).slice(0, 100)}`,
      rerun: 'already-tried',
      at: now.toISOString()
    }], file, () => now)

    return { ok: false, rerun: 'already-tried', error: err?.message }
  }
}

// Handle a webhook request to trigger a no-runner rerun. Expected body shape: {pr_url, number, sha, runId, checkName}.
// Never throws.
export async function handleNoRunnerRerunRequest({ method, url, body }, { exec, file = NO_RUNNER_RERUN_PATH, knownRepos = [] } = {}) {
  if (method !== 'POST' || url !== '/no-runner-rerun') {
    return { status: 404, json: { ok: false } }
  }

  let payload
  try {
    payload = typeof body === 'string' ? JSON.parse(body) : body
  } catch {
    return { status: 400, json: { ok: false, error: 'invalid JSON' } }
  }

  const prUrl = typeof payload?.pr_url === 'string' ? payload.pr_url : null
  const number = typeof payload?.number === 'number' ? payload.number : null
  const sha = typeof payload?.sha === 'string' ? payload.sha : null
  const runId = typeof payload?.runId === 'string' || typeof payload?.runId === 'number' ? String(payload.runId) : null
  const checkName = typeof payload?.checkName === 'string' ? payload.checkName : null

  if (!prUrl || !number || !sha || !runId || !checkName) {
    return { status: 400, json: { ok: false, error: 'missing required fields: pr_url, number, sha, runId, checkName' } }
  }

  const match = /^https:\/\/github\.com\/([^/]+\/[^/]+)\/pull\//.exec(prUrl)
  const repo = match ? match[1] : null
  if (!repo) {
    return { status: 400, json: { ok: false, error: 'invalid pr_url' } }
  }

  // Security: only allow reruns for known/mergeable repos (even if list is empty, only allow if it contains the repo)
  // This prevents accepting any repo when the queue hasn't loaded yet.
  if (!knownRepos.includes(repo)) {
    return { status: 403, json: { ok: false, error: 'not a known repo' } }
  }

  // Validate that the runId belongs to this commit (prevent arbitrary rerun requests)
  // Fetch the check runs for this commit and verify the runId exists for the requested checkName
  try {
    const { stdout } = await exec('gh', ['api', `repos/${repo}/commits/${sha}/check-runs`, '--paginate', '--jq', '.check_runs[] | select(.name == "' + checkName.replace(/"/g, '\\"') + '") | .id'])
    const matchingRunId = stdout.trim()
    if (!matchingRunId || matchingRunId !== runId) {
      return { status: 400, json: { ok: false, error: 'runId does not belong to this commit' } }
    }
  } catch {
    return { status: 400, json: { ok: false, error: 'could not validate runId for commit' } }
  }

  const result = await triggerNoRunnerRerun({ repo, number, sha, runId, checkName, exec, file })
  return { status: result.ok ? 200 : 500, json: result }
}
