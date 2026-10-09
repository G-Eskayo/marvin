// Derives a horizontal strip of stage segments from latest-per-stage events.
// Input: stages = { stage_key: latest_event_for_that_stage }
// Output: array of { key, label, status: pending|started|stalled|passed|failed, message, remediation, timestamp, machine, cost_usd }
// A stage is skipped if its event's stage key is unknown (forward compat for future stages).
// A failed event whose detail matches /^refused <CODE>:/ shows that CODE's label, message only (no fabricated remediation for OUT_OF_ORDER etc).

// Note: REMEDIATION_BY_CODE is imported from the webhook (shared source); additional codes from refusal() call sites are defined here
// to keep them in sync. This prevents the dashboard and webhook from silently diverging on remediation messages.
// See webhook-server/failure.js and dashboard/test/refusal_log.test.js for all refusal codes.

const VALID_STAGES_ORDERED = ['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging', 'rebuilding', 'done']

const STAGE_LABEL = {
  claimed: 'Claimed',
  planning: 'Planning',
  executing: 'Executing',
  verifying: 'Verifying',
  gate: 'Gate',
  merging: 'Merging',
  rebuilding: 'Rebuilding',
  done: 'Done',
}

// Codes mapped from webhook-server/failure.js RULES + refusal() call sites.
// RULES are the automatic classifyFailure codes; refusal() codes come from explicit checks in merge.js/ci_status.js.
// KEEP IN SYNC with webhook-server/failure.js RULES and all refusal() call sites in merge.js and ci_status.js.
const REMEDIATION_BY_CODE = {
  GH_AUTH_INVALID: 'GitHub rejected the credential. Fix ~/.claude/.gh-token on the machine running the webhook (the Health tab shows auth:gh per machine).',
  NOT_MERGEABLE: 'The PR conflicts with main. It was sent back to its ticket for rework.',
  BRANCH_PROTECTION: 'Branch protection blocked the merge. Satisfy the required checks/reviews, or adjust the rule.',
  BASE_MOVED: 'main moved while this merged. Retried automatically; if it keeps failing, another merge is racing it.',
  RATE_LIMITED: 'GitHub rate limit. Retried automatically with backoff; try again shortly if it persists.',
  GITHUB_OUTAGE: 'GitHub is having an outage (githubstatus.com). Nothing is wrong with this PR and it was not sent back; approve again once GitHub recovers.',
  TRANSIENT_NETWORK: 'Transient network or GitHub error. Retried automatically; check connectivity if it persists.',
  TOOL_MISSING: "A required tool (gh/git/npm) is missing from the webhook's PATH. Install it or fix the launchd plist PATH.",
  PR_NOT_FOUND: 'GitHub has no such pull request. It may have been closed or deleted, or the URL is wrong.',
  INVALID_REQUEST: 'The request did not contain a valid GitHub PR URL.',
  NO_MERGE_PROFILE: 'The project has no merge profile defined. Add one.',
  WRONG_BASE: 'The PR targets the wrong base branch.',
  SENT_BACK: 'The PR was sent back from review.',
  CI_PENDING: "GitHub's checks are still running.",
  CI_FAILED: "GitHub's checks failed on this PR.",
  REBASE_CONFLICT: 'Rebasing onto main produced a conflict that must be resolved manually.',
  GATE_TESTS_FAILED: 'Tests failed on this PR. Review the output and fix them.',
  MAIN_RED: 'main is currently red (tests failing). Approve again once main is green.',
  GATE_INFRA: 'The build machine or test setup failed. This is not a problem with the PR itself.',
  MERGE_REFUSED: 'GitHub refused the merge but does not report a conflict on this PR.',
  ENV_MISSING: 'This machine lacks required tools for the verification checks.',
}

// Refusal codes that show message-only, no remediation (codes not in the table above)
const REFUSAL_MESSAGE_ONLY = new Set([
  'OUT_OF_ORDER',  // has a specific message like "Merge #208 first", no generic remediation
])

export function deriveSegments(stages, { rebase, isLiveNow, now, stallMinutes = 30 } = {}) {
  const segments = []
  let latestTimestamp = 0

  // Process each valid stage in order
  for (const stageKey of VALID_STAGES_ORDERED) {
    const event = stages[stageKey]
    if (!event) continue
    if (event.stage !== stageKey) continue // Sanity check

    latestTimestamp = Math.max(latestTimestamp, new Date(event.timestamp).getTime())

    let status = 'pending'
    let message = ''
    let remediation = null

    if (event.status === 'passed') {
      status = 'passed'
    } else if (event.status === 'failed') {
      status = 'failed'
      const code = extractRefusalCode(event.detail) || extractCodeFromDetail(event.detail)
      message = extractMessageFromDetail(event.detail)
      if (code && REFUSAL_MESSAGE_ONLY.has(code)) {
        remediation = null // Message only, no generic remediation
      } else if (code && REMEDIATION_BY_CODE[code]) {
        remediation = REMEDIATION_BY_CODE[code]
      } else if (REMEDIATION_BY_CODE[event.detail]) {
        remediation = REMEDIATION_BY_CODE[event.detail]
      }
    } else if (event.status === 'started') {
      // Started: check if live or stalled
      try {
        const isLive = typeof isLiveNow === 'function' ? isLiveNow() : isLiveNow
        const elapsedMs = now - new Date(event.timestamp).getTime()
        const stalledMs = stallMinutes * 60 * 1000
        status = isLive && elapsedMs < stalledMs ? 'started' : 'stalled'
      } catch {
        status = 'stalled' // Default to stalled if isLiveNow fails
      }
    }

    const refusalLabel = extractRefusalLabel(event.detail)
    const label = refusalLabel ? refusalLabel : STAGE_LABEL[stageKey]

    segments.push({
      key: stageKey,
      label,
      status,
      message,
      remediation,
      timestamp: event.timestamp,
      machine: event.machine,
      cost_usd: event.cost_usd,
    })
  }

  // Handle rebase prop
  if (rebase && rebase.status === 'conflict') {
    segments.push({
      key: 'rebase',
      label: 'Rebase',
      status: 'failed',
      message: `Conflict on ${rebase.files?.join(', ') || 'files'}`,
      remediation: 'Resolve the conflict and push.',
      timestamp: new Date(now).toISOString(),
      machine: null,
      cost_usd: null,
    })
  }

  return segments
}

function extractMessageFromDetail(detail) {
  if (!detail) return ''
  // If it starts with "refused <CODE>:" or "<CODE>:", extract the reason part
  const match = detail.match(/^(?:refused )?[A-Z_]+: (.*)$/)
  return match ? match[1] : detail
}

function extractRefusalCode(detail) {
  if (!detail) return null
  const match = detail.match(/^refused ([A-Z_]+):/)
  return match ? match[1] : null
}

function extractCodeFromDetail(detail) {
  if (!detail) return null
  // Extract a code like "GATE_TESTS_FAILED: ..." or "REBASE_CONFLICT: ..."
  const match = detail.match(/^([A-Z_]+):/)
  return match ? match[1] : null
}

function extractRefusalLabel(detail) {
  if (!detail) return null
  const match = detail.match(/^refused ([A-Z_]+):/)
  if (!match) return null
  const code = match[1]
  // Map refusal codes to display labels
  const labelMap = {
    OUT_OF_ORDER: 'Order check',
    NOT_MERGEABLE: 'Merging',
    WRONG_BASE: 'Merging',
    SENT_BACK: 'Merging',
    CI_PENDING: 'Merging',
    CI_FAILED: 'Merging',
  }
  return labelMap[code] || null
}
