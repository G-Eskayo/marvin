// Canonical code information table for approval/merge failures.
// Single source of truth for label, remediation, and whether the code needs human attention.
// Used across the main process, webhook, and dashboard to ensure consistent messaging.

export const CODE_INFO = {
  // Merge/approval refusals from failure.js patterns (gh/git errors, GitHub states)
  GH_AUTH_INVALID: { label: 'GitHub auth invalid', remediation: 'GitHub rejected the credential. Fix ~/.claude/.gh-token on the machine running the webhook (the Health tab shows auth:gh per machine).', needsYou: true },
  NOT_MERGEABLE: { label: 'Not mergeable', remediation: 'The PR conflicts with main. It was sent back to its ticket for rework.', needsYou: false },
  PR_DRAFT: { label: 'PR is a draft', remediation: 'The PR is a draft. Mark it "Ready for review" on GitHub, then approve again. The PR was not sent back.', needsYou: true },
  BRANCH_PROTECTION: { label: 'Branch protection blocked', remediation: 'Branch protection blocked the merge. Satisfy the required checks/reviews, or adjust the rule.', needsYou: true },
  BASE_MOVED: { label: 'Base branch moved', remediation: 'main moved while this merged. Retried automatically; if it keeps failing, another merge is racing it.', needsYou: false },
  RATE_LIMITED: { label: 'Rate limited', remediation: 'GitHub rate limit. Retried automatically with backoff; try again shortly if it persists.', needsYou: false },
  GITHUB_OUTAGE: { label: 'GitHub outage', remediation: 'GitHub is having an outage (githubstatus.com). Nothing is wrong with this PR and it was not sent back; approve again once GitHub recovers.', needsYou: false },
  TRANSIENT_NETWORK: { label: 'Network error', remediation: 'Transient network or GitHub error. Retried automatically; check connectivity if it persists.', needsYou: false },
  TOOL_MISSING: { label: 'Tool missing', remediation: "A required tool (gh/git/npm) is missing from the webhook's PATH. Install it or fix the launchd plist PATH.", needsYou: true },
  PR_NOT_FOUND: { label: 'PR not found', remediation: 'GitHub has no such pull request. It may have been closed or deleted, or the URL is wrong.', needsYou: true },
  INVALID_REQUEST: { label: 'Invalid request', remediation: 'The request did not contain a valid GitHub PR URL.', needsYou: true },

  // Inline refusals from merge.js and decisions.js
  OUT_OF_ORDER: { label: 'Out of order', remediation: 'Another PR must merge first. See the blockedBy list on this ticket.', needsYou: true },
  WRONG_BASE: { label: 'Wrong base branch', remediation: 'The PR is not based on main. Rebase onto main before approving.', needsYou: true },
  SENT_BACK: { label: 'Sent back', remediation: 'The PR was sent back to its ticket for rework.', needsYou: false },
  CI_PENDING: { label: 'CI pending', remediation: 'CI checks are still running. Approve again once they pass.', needsYou: false },
  NO_MERGE_PROFILE: { label: 'No merge profile', remediation: 'This project has no merge profile configured. Add one in the project settings.', needsYou: true },
  MERGE_REFUSED: { label: 'Merge refused', remediation: 'The merge was refused. See the ticket for details.', needsYou: true },
  CI_FAILED: { label: 'CI failed', remediation: 'CI failed. Fix the failing tests and approve again.', needsYou: true },
  GATE_INFRA: { label: 'Build machine failed', remediation: 'The merge gate infrastructure failed (no test command, full disk, database locked). Retry once fixed.', needsYou: false },
  MEMORY_PRESSURE: { label: 'Memory pressure', remediation: "The Mac's memory is under pressure, so the check waits. It starts by itself when pressure drops; nothing was stopped.", needsYou: false },
  MAIN_RED: { label: 'main failing', remediation: 'main branch is failing tests. Approve again once main is green.', needsYou: false },
  GATE_TESTS_FAILED: { label: 'Tests failed', remediation: 'Tests failed in the merge gate. Fix the failing tests and approve again.', needsYou: true },
  VERSION_BUMP_FAILED: { label: 'Version bump failed', remediation: 'Version bump failed. Check the CHANGELOG format and ticket metadata.', needsYou: true },
  REBASE_CONFLICT: { label: 'Rebase conflict', remediation: 'Needs a person to rebase by hand until #230 can resolve it automatically.', needsYou: true },
  IMAGES_STALE: { label: 'Images stale', remediation: 'Screenshot images are older than the latest code change. Re-pin images or ignore if intentional.', needsYou: true },
  UNKNOWN: { label: 'Unknown error', remediation: 'Unclassified failure. See the evidence; this needs triage.', needsYou: true }
}

export function plainLabel(code) {
  return code ? CODE_INFO[code]?.label ?? CODE_INFO.UNKNOWN.label : CODE_INFO.UNKNOWN.label
}

export function remediationFor(code) {
  return code ? CODE_INFO[code]?.remediation ?? CODE_INFO.UNKNOWN.remediation : CODE_INFO.UNKNOWN.remediation
}

export function needsYouFor(code) {
  return code ? CODE_INFO[code]?.needsYou ?? CODE_INFO.UNKNOWN.needsYou : CODE_INFO.UNKNOWN.needsYou
}

// Backward-compatibility export: maps code → remediation (used by stage_strip.js and mr_history.js)
export const REMEDIATION_BY_CODE = Object.fromEntries(
  Object.entries(CODE_INFO).map(([code, info]) => [code, info.remediation])
)
