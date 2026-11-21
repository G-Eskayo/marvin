// Detect and classify GitHub checks that mark themselves as "no-runner" (not applicable, skipped, or not run).
// A check that records no-runner via an annotation never holds a PR: the merge gate will run what it needs.

export function isNoRunnerAnnotation(annotation) {
  if (!annotation || typeof annotation !== 'object') return false
  const title = String(annotation.title || '').toLowerCase()
  const msg = String(annotation.message || '').toLowerCase()
  // Common patterns from GitHub's built-in checks and Actions workflows that mark themselves as skipped/not run.
  // Be specific to avoid matching error messages that just happen to contain these words.
  // Check for explicit "this check was skipped" rather than "test results: X skipped, Y failed"
  const checkSkipped = /(check|test|job|task|workflow).*\bskipped\b|\bskipped\b.*(check|test|job|task|workflow)/i.test(title + ' ' + msg)
  || title === 'skipped' // explicit title "Skipped"
  const notRunWord = /\b(not run|not.?run)\b/i.test(title) || /\b(not run|not.?run)\b/i.test(msg)
  const noRunnerWord = /\bno.?runner\b/i.test(title) || /\bno.?runner\b/i.test(msg)
  // Platform constraints: "platform not supported", "unsupported platform", "platform unavailable", etc.
  const platformUnsupported = /\b(platform|system|runner|runner|environment)\b.*\b(not supported|unsupported|unavailable|not available)\b|\b(not supported|unsupported|unavailable|not available)\b.*\b(platform|system|runner|environment)\b/i.test(title + ' ' + msg)
  return checkSkipped || notRunWord || noRunnerWord || platformUnsupported
}

export function isNoRunnerCheck(checkRun) {
  if (!checkRun || typeof checkRun !== 'object') return false
  // A check marked SKIPPED, NEUTRAL (skipped-like), or with conclusion STALE (timed out but not counted as failure)
  const conclusion = String(checkRun.conclusion || '').toUpperCase()
  if (conclusion === 'SKIPPED' || conclusion === 'STALE' || conclusion === 'NEUTRAL') return true
  // A check that explicitly recorded its no-runner status in its title.
  // The title is set by the check itself to indicate its status, so it's more reliable than the summary.
  const title = String(checkRun.title || '').toLowerCase()
  if (title === 'skipped' || title === 'not run' || title === 'not applicable') return true
  // Summary should be checked carefully to avoid matching test result summaries like "12 passed, 1 skipped".
  // Only match if it's about the check itself, not test counts: "this check was skipped", "Platform not supported, check not run"
  const summary = String(checkRun.summary || '').toLowerCase()
  if (summary.startsWith('skipped') || summary.startsWith('not applicable') || summary.startsWith('not run')) return true
  if (/(check|job|task).*\b(skipped|not run|not applicable)\b/i.test(summary)) return true
  if (/^platform.*(not supported|unavailable)/i.test(summary)) return true
  return false
}

export function runIdFromDetailsUrl(url) {
  if (!url || typeof url !== 'string') return null
  // GitHub Actions URL format: https://github.com/OWNER/REPO/actions/runs/RUN_ID[/attempts/ATTEMPT]
  const match = /\/actions\/runs\/(\d+)/.exec(url)
  return match ? match[1] : null
}

export async function fetchCommitCheckRuns({ repo, sha, exec }) {
  if (!repo || !sha || !exec) return []
  if (!/^[0-9a-f]{40}$/.test(sha)) return []
  try {
    const { stdout } = await exec('gh', ['api', `repos/${repo}/commits/${sha}/check-runs`, '--paginate', '--jq', '.check_runs[] | {id: .id, name: .name, status: .status, conclusion: .conclusion, startedAt: .started_at, completedAt: .completed_at, detailsUrl: .details_url, summary: .output.summary, title: .output.title}'])
    return stdout.trim() ? stdout.split('\n').map(line => {
      try {
        return JSON.parse(line)
      } catch {
        return null
      }
    }).filter(Boolean) : []
  } catch {
    return []
  }
}

export async function fetchCheckAnnotations({ repo, runId, exec }) {
  if (!repo || !runId || !exec) return []
  try {
    const { stdout } = await exec('gh', ['api', `repos/${repo}/check-runs/${runId}/annotations`, '--paginate', '--jq', '.[] | {title: .title, message: .message, level: .annotation_level}'])
    return stdout.trim() ? stdout.split('\n').map(line => {
      try {
        return JSON.parse(line)
      } catch {
        return null
      }
    }).filter(Boolean) : []
  } catch {
    return []
  }
}

// Classify which failing checks are no-runner (and therefore do not hold the PR).
// Returns { noRunner: [name1, name2, ...], other: [name3, ...] }
// Never throws.
export async function classifyFailingChecks({ repo, sha, failingNames, exec }) {
  if (!Array.isArray(failingNames) || !failingNames.length) return { noRunner: [], other: failingNames || [] }

  const noRunner = []
  const other = []

  try {
    const checkRuns = await fetchCommitCheckRuns({ repo, sha, exec })
    const checksByName = new Map(checkRuns.map(c => [String(c.name || '').trim(), c]))

    for (const name of failingNames) {
      const run = checksByName.get(String(name || '').trim())
      if (!run) {
        other.push(name)
        continue
      }

      // Check the run's conclusion first
      if (isNoRunnerCheck(run)) {
        noRunner.push(name)
        continue
      }

      // Check annotations: a failed check with a no-runner annotation (e.g. "platform not supported")
      // is a no-runner check, not a real failure. Annotations take precedence over conclusion.
      let isNoRunnerViaAnnotation = false
      if (run.id) {
        const annotations = await fetchCheckAnnotations({ repo, runId: run.id, exec })
        if (annotations.length && annotations.some(isNoRunnerAnnotation)) {
          isNoRunnerViaAnnotation = true
        }
      }

      if (isNoRunnerViaAnnotation) {
        noRunner.push(name)
        continue
      }

      // If the check's conclusion indicates a real failure, it's a real failure
      const conclusion = String(run.conclusion || '').toUpperCase()
      const FAILED = new Set(['FAILURE', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE'])
      if (FAILED.has(conclusion)) {
        other.push(name)
        continue
      }

      // For other cases (pending, etc.), treat as other
      other.push(name)
    }
  } catch {
    // On error, treat all as "other" (let the merge gate decide)
    return { noRunner: [], other: failingNames }
  }

  return { noRunner, other }
}
