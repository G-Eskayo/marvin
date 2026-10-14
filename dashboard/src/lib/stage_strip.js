// Derives a compact visual summary of a ticket/PR's progression through the pipeline from its event log.
// Pure function: no I/O, no side effects, fully testable against real event logs.

import { STAGE_ORDER, STAGE_LABEL } from '../../webhook-server/stage_vocabulary'

export const VALID_STAGES = STAGE_ORDER
export { STAGE_LABEL }

const REFUSAL_REMEDIATION = {
  OUT_OF_ORDER: 'Merge the blocking ticket first, then try this one again.',
  WRONG_BASE: 'Rebase this branch onto main and push; check if the issue still applies.',
  SENT_BACK: 'A previous pass found issues; rework the ticket as directed and re-propose.',
  CI_PENDING: 'Wait for the in-flight CI checks to finish, then try again.',
  NO_MERGE_PROFILE: 'This project has no merge profile in the dashboard config. Add one to proceed.',
  MERGE_REFUSED: 'GitHub refused the merge. Check the PR for details (typically branch protection).',
  GATE_INFRA: 'Infrastructure issue with the merge gate. Escalate to the operator.',
  GATE_TESTS_FAILED: 'Tests are failing on this branch. Fix the failure and push again.',
  MAIN_RED: 'Main is currently failing its own tests. Wait for main to be fixed, then try again.',
  CI_FAILED: 'CI checks failed. Fix the failures and push again.',
  REBASE_CONFLICT: 'This branch conflicts with main. Resolve conflicts, rebase, and push.',
  TRANSIENT_NETWORK: 'Temporary network issue. Try again shortly.',
  RATE_LIMITED: 'GitHub API rate limit reached. Wait a moment and try again.',
  GITHUB_OUTAGE: 'GitHub appears to be unavailable. Check status and try again.',
  TOOL_MISSING: 'A required tool is not available on the merge machine. Contact support.',
  GH_AUTH_INVALID: 'GitHub authentication failed. Check your token and try again.',
  BRANCH_PROTECTION: 'Branch protection prevents this merge. Review the branch protection rules.',
  PR_NOT_FOUND: 'PR not found. Verify the URL and try again.',
  INVALID_REQUEST: 'Invalid request to the merge gate. Check the PR details.',
  VERSION_BUMP_FAILED: 'Version bump or changelog update failed. Fix the issue and push again.',
  DRAFT_READY: 'Draft marked ready for review.',
  PR_DRAFT: 'This PR is still in draft mode. Mark it "Ready for review" on GitHub.',
  ENV_MISSING: 'Environment variable or configuration is missing. Contact the operator.',
  BASE_MOVED: 'The base branch moved. Rebase onto main and push.'
}

function statusOfEvent(event, isLiveNow, stallMinutes = 30, now = Date.now()) {
  const { status, timestamp } = event
  if (status !== 'started' || !isLiveNow) return status === 'started' ? 'stalled' : status
  if (!timestamp) return 'stalled'
  try {
    const elapsed = (now - new Date(timestamp).getTime()) / 60000
    return elapsed < stallMinutes ? 'started' : 'stalled'
  } catch {
    return 'stalled'
  }
}

function parseRefusal(detail) {
  const match = detail.match(/^refused\s+(\w+):\s*(.*)$/)
  if (!match) return null
  return { code: match[1], message: match[2] }
}

export function deriveSegments(
  events,
  {
    now = Date.now(),
    isLiveNow = false,
    stallMinutes = 30,
    checks = null,
    conflicts = false,
    sentBack = false
  } = {}
) {
  if (!Array.isArray(events)) return []

  const segments = []
  const eventsByStage = new Map()
  let refusalSegment = null

  // Group events by stage in array order (not timestamp order)
  for (const event of events) {
    if (!VALID_STAGES.includes(event.stage)) continue
    if (!eventsByStage.has(event.stage)) eventsByStage.set(event.stage, [])
    eventsByStage.get(event.stage).push(event)
  }

  // Render each stage in the correct order
  for (const stage of VALID_STAGES) {
    const stageEvents = eventsByStage.get(stage)
    if (!stageEvents || stageEvents.length === 0) continue

    // Use the latest event for this stage
    const latest = stageEvents[stageEvents.length - 1]
    const status = statusOfEvent(latest, isLiveNow, stallMinutes, now)

    // Special handling for merging stage: check for refusals
    if (stage === 'merging' && latest.detail && latest.detail.startsWith('refused')) {
      const refusal = parseRefusal(latest.detail)
      if (refusal) {
        const isOrder = refusal.code === 'OUT_OF_ORDER' || refusal.code === 'WRONG_BASE'
        const refusalStage = isOrder ? 'order' : 'request'
        refusalSegment = {
          stage: refusalStage,
          status: 'failed',
          label: isOrder ? 'Order' : 'Request',
          message: refusal.message,
          remediation: REFUSAL_REMEDIATION[refusal.code] || REFUSAL_REMEDIATION.MERGE_REFUSED,
          events: stageEvents,
          cost: stageEvents.reduce((sum, e) => sum + (e.cost_usd || 0), 0)
        }
      } else {
        segments.push({
          stage,
          status,
          label: STAGE_LABEL[stage],
          message: latest.detail,
          events: stageEvents,
          cost: stageEvents.reduce((sum, e) => sum + (e.cost_usd || 0), 0)
        })
      }
    } else {
      segments.push({
        stage,
        status,
        label: STAGE_LABEL[stage],
        message: latest.detail || null,
        events: stageEvents,
        cost: stageEvents.reduce((sum, e) => sum + (e.cost_usd || 0), 0)
      })
    }
  }

  // Insert refusal segment at the correct position (before gate or end if no gate yet)
  if (refusalSegment) {
    const insertIdx = segments.findIndex(s => VALID_STAGES.indexOf(s.stage) >= VALID_STAGES.indexOf('gate'))
    if (insertIdx >= 0) {
      segments.splice(insertIdx, 0, refusalSegment)
    } else {
      segments.push(refusalSegment)
    }
  }

  // Synthetic segments from live PR state (not in the event log)
  if (checks) {
    const { state, failing = [], pending = [] } = checks
    let status = 'pending'
    let message = ''
    if (state === 'passing') status = 'passed'
    else if (state === 'failing') {
      status = 'failed'
      message = failing.length ? `Failing: ${failing.join(', ')}` : 'Check failed'
    } else if (state === 'pending') {
      status = 'started'
      message = pending.length ? `Pending: ${pending.join(', ')}` : 'Checks in progress'
    }
    // Insert checks just before gate
    const gateIdx = segments.findIndex((s) => s.stage === 'gate')
    const checkSegment = {
      stage: 'checks',
      status,
      label: 'Checks',
      message,
      events: [],
      cost: 0
    }
    if (gateIdx >= 0) segments.splice(gateIdx, 0, checkSegment)
    else segments.push(checkSegment)
  }

  // Rebase status (conflicts but not sent back)
  if (conflicts && !sentBack && isLiveNow === false) {
    segments.push({
      stage: 'needs-rebase',
      status: 'blocked',
      label: 'Needs rebase',
      message: 'This branch conflicts with main',
      remediation: 'Rebase this branch onto main and push; the pipeline won\'t do this one automatically.',
      events: [],
      cost: 0
    })
  }

  return segments
}
