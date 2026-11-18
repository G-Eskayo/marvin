import { failingCheckRuns } from '../../webhook-server/ci_status.js'
import { parseRunAndJobId, classifyFailure, fetchAnnotations } from '../../webhook-server/check_annotations.js'
import { noRunnerKey, readNoRunnerReruns, recordNoRunnerRerun, NO_RUNNER_RERUN_PATH } from '../../webhook-server/no_runner_rerun.js'

// The no-runner safety net: automatically reruns checks that failed due to runner capacity,
// not code. Each PR is inspected per refresh; a no-runner check is rerun once per head SHA,
// then tracked to avoid rerunning it again.
export function createNoRunnerRetry({ gh, gateCoversFor = () => null, now = Date.now, log = (m) => console.error(m) }) {
  return {
    async check(prs) {
      const reruns = readNoRunnerReruns(NO_RUNNER_RERUN_PATH)
      for (const pr of (prs || [])) {
        try {
          await checkOneRun(pr, gh, gateCoversFor, now, log, reruns)
        } catch (e) {
          log(`[no-runner-retry] Error checking PR #${pr.number}: ${String(e?.message || e).slice(0, 200)}`)
        }
      }
    }
  }
}

async function checkOneRun(pr, gh, gateCoversFor, now, log, reruns) {
  const rollup = pr.statusCheckRollup || []
  const gates = gateCoversFor(pr.repo) || []
  const failing = failingCheckRuns(rollup, { ignore: gates })

  // If any check has a real FAILURE conclusion, skip the whole PR (don't show no-runner)
  if (failing.some((c) => c.conclusion === 'FAILURE')) return

  for (const check of failing) {
    // Extract run and job IDs from the check's details URL
    const ids = parseRunAndJobId(check.detailsUrl)
    if (!ids) continue

    const key = noRunnerKey(pr.repo, pr.number, pr.headRefOid, ids.runId)
    const existing = reruns[key]

    // Already handled: either reran, asked, or refused
    if (existing) {
      if (existing.result === 'refused') continue
      if (existing.result === 'asked') continue
      if (existing.result === 'reran') {
        // Mark as "asked" so we don't rerun again
        existing.result = 'asked'
        recordNoRunnerRerun(key, existing, NO_RUNNER_RERUN_PATH, () => new Date(now()))
      }
      continue
    }

    // First sighting: fetch annotations to verify this is truly no-runner
    let annotations = []
    try {
      annotations = await fetchAnnotations(pr.repo, ids.jobId, gh)
    } catch (e) {
      log(`[no-runner-retry] Failed to fetch annotations for PR #${pr.number}: ${String(e?.message || e).slice(0, 200)}`)
      continue
    }

    const classified = classifyFailure(annotations)
    if (classified !== 'no-runner') continue

    // Rerun the check
    const at = new Date(now()).toISOString()
    try {
      await gh(['run', 'rerun', ids.runId, '--repo', pr.repo, '--failed'])
      recordNoRunnerRerun(key, { result: 'reran', at }, NO_RUNNER_RERUN_PATH, () => new Date(now()))
    } catch (e) {
      // Rerun failed (rate limit, permission): record refusal so we don't retry
      recordNoRunnerRerun(key, { result: 'refused', at }, NO_RUNNER_RERUN_PATH, () => new Date(now()))
      log(`[no-runner-retry] Rerun refused for PR #${pr.number}: ${String(e?.message || e).slice(0, 200)}`)
    }
  }
}
