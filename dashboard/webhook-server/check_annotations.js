// Parses GitHub Actions check run details to classify no-runner vs real failures.
// All functions are pure + best-effort (never throw).

// Extract runId and jobId from a GitHub Actions URL like:
// https://github.com/owner/repo/actions/runs/123/job/456
export function parseRunAndJobId(url) {
  if (!url || typeof url !== 'string') return null
  if (!url.includes('github.com')) return null
  const match = url.match(/\/actions\/runs\/(\d+)\/job\/(\d+)/)
  return match ? { runId: match[1], jobId: match[2] } : null
}

// Known no-runner annotation titles (from GitHub's standard messages).
const NO_RUNNER_PATTERNS = [
  /not acquired by [Rr]unner/i,
  /could not be acquired by the runner/i,
  /the action is not available/i,
  /runner.*offline/i,
  /cancelled.*github/i
]

export function isNoRunnerAnnotation(annotation) {
  if (!annotation || !annotation.title) return false
  return NO_RUNNER_PATTERNS.some((p) => p.test(annotation.title))
}

// Classify a check's failure: 'no-runner' if all annotations are no-runner wording or no annotations at all,
// 'failure' if real annotations found, 'unknown' if unable to fetch (null).
export function classifyFailure(annotations) {
  if (annotations === null) return 'unknown'
  if (!Array.isArray(annotations)) return 'failure'
  if (annotations.length === 0) return 'no-runner'
  if (annotations.every((a) => isNoRunnerAnnotation(a))) return 'no-runner'
  return 'failure'
}

// Fetch annotations for a check run from GitHub. Returns array of annotations, null on network/404 errors.
// Never throws. Returns [] if parsing fails (unexpected format).
export async function fetchAnnotations(repo, jobId, gh) {
  let json
  try {
    json = await gh(['api', `repos/${repo}/check-runs/${jobId}/annotations`, '--paginate'])
  } catch {
    return null
  }
  try {
    const parsed = JSON.parse(json)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}
