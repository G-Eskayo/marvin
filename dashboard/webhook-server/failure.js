// Structured failures for the approve/merge path.
//
// Before: an approve failure reached the dashboard as "Webhook call failed: 500" and
// reached the pipeline as a raw stderr wall, so neither a human nor an automated
// consumer could act on it (found 2026-10-02 while chasing "MRs aren't merging").
// Now every failure carries a stable CODE, the STAGE it happened at, whether it is
// RETRYABLE, and a next ACTION the pipeline can take without parsing prose:
//   retry    -- transient; the server already retried with backoff
//   reengage -- the ticket's work needs changing; sent back to the ticket with detail
//   escalate -- needs a human (credentials, tooling, branch protection, unknown)

const RULES = [
  { code: 'GH_AUTH_INVALID', action: 'escalate', retryable: false,
    test: /bad credentials|http 401|authentication failed|could not read username|requires authentication|token.*(invalid|expired)|invalid.*token/i,
    remediation: 'GitHub rejected the credential. Fix ~/.claude/.gh-token on the machine running the webhook (the Health tab shows auth:gh per machine).' },
  { code: 'NOT_MERGEABLE', action: 'reengage', retryable: false,
    test: /not mergeable|merge conflict|conflicts? must be resolved|cannot be merged/i,
    remediation: 'The PR conflicts with main. It was sent back to its ticket for rework.' },
  // GitHub will not merge a draft. The gate marks an owner-approved draft ready first (readyIfDraft in merge.js);
  // this catches one that slipped through, so it is named instead of UNKNOWN (clarity-captions #77/#78, 2026-10-09).
  { code: 'PR_DRAFT', action: 'escalate', retryable: false,
    test: /is still a draft|pull request is a draft|draft pull request/i,
    remediation: 'The PR is a draft. Mark it "Ready for review" on GitHub, then approve again. The PR was not sent back.' },
  { code: 'BRANCH_PROTECTION', action: 'escalate', retryable: false,
    test: /protected branch|required status check|required review|branch protection|gh006|gh013/i,
    remediation: 'Branch protection blocked the merge. Satisfy the required checks/reviews, or adjust the rule.' },
  // GitHub refuses a merge when the base branch moved between it checking and merging (two merges close
  // together). Nothing is wrong with the PR; trying again, once main has settled, is the right response.
  { code: 'BASE_MOVED', action: 'retry', retryable: true,
    test: /base branch was modified|try the merge again/i,
    remediation: 'main moved while this merged. Retried automatically; if it keeps failing, another merge is racing it.' },
  { code: 'RATE_LIMITED', action: 'retry', retryable: true,
    test: /rate limit|secondary rate|abuse detection/i,
    remediation: 'GitHub rate limit. Retried automatically with backoff; try again shortly if it persists.' },
  // GitHub itself failing (an incident, not our network): its own 5xx answers. Seen 2026-10-07 when a rebase push
  // died with "remote: Internal Server Error" after a full retest. The PR is fine; waiting and retrying is the answer.
  { code: 'GITHUB_OUTAGE', action: 'retry', retryable: true,
    test: /internal server error|http 500|returned error: 50[0-4]/i,
    remediation: 'GitHub is having an outage (githubstatus.com). Nothing is wrong with this PR and it was not sent back; approve again once GitHub recovers.' },
  { code: 'TRANSIENT_NETWORK', action: 'retry', retryable: true,
    test: /econnreset|etimedout|enotfound|econnrefused|eai_again|socket hang up|network|timed out|http 50[234]|bad gateway|service unavailable|gateway time-?out/i,
    remediation: 'Transient network or GitHub error. Retried automatically; check connectivity if it persists.' },
  { code: 'TOOL_MISSING', action: 'escalate', retryable: false,
    test: /enoent|command not found|no such file or directory.*(gh|git|npm|npx)/i,
    remediation: "A required tool (gh/git/npm) is missing from the webhook's PATH. Install it or fix the launchd plist PATH." },
  { code: 'PR_NOT_FOUND', action: 'escalate', retryable: false,
    test: /could not resolve to a pullrequest|pull request not found|no pull requests? found/i,
    remediation: 'GitHub has no such pull request. It may have been closed or deleted, or the URL is wrong.' },
  { code: 'INVALID_REQUEST', action: 'escalate', retryable: false,
    test: /not a github pr url/i,
    remediation: 'The request did not contain a valid GitHub PR URL.' }
]

// Canonical failure codes: every code that classifyFailure, refusal, or summarizeGateFailure can return.
// Exported for dashboard, history, and UI rendering. Each entry has: reason (human text), remediation,
// needsYou (true = human action required, false = automatic/infrastructure), action ('reengage', 'retry', or 'escalate').
export const FAILURE_TABLE = {
  // From RULES: error-pattern matches (11 codes)
  GH_AUTH_INVALID: { reason: 'GitHub rejected the credential', remediation: 'GitHub rejected the credential. Fix ~/.claude/.gh-token on the machine running the webhook (the Health tab shows auth:gh per machine).', needsYou: true, action: 'escalate' },
  NOT_MERGEABLE: { reason: 'PR conflicts with main', remediation: 'The PR conflicts with main. It was sent back to its ticket for rework.', needsYou: true, action: 'reengage' },
  PR_DRAFT: { reason: 'PR is a draft', remediation: 'The PR is a draft. Mark it "Ready for review" on GitHub, then approve again. The PR was not sent back.', needsYou: true, action: 'escalate' },
  BRANCH_PROTECTION: { reason: 'Branch protection blocked the merge', remediation: 'Branch protection blocked the merge. Satisfy the required checks/reviews, or adjust the rule.', needsYou: true, action: 'escalate' },
  BASE_MOVED: { reason: 'main moved while this merged', remediation: 'main moved while this merged. Retried automatically; if it keeps failing, another merge is racing it.', needsYou: false, action: 'retry' },
  RATE_LIMITED: { reason: 'GitHub rate limit', remediation: 'GitHub rate limit. Retried automatically with backoff; try again shortly if it persists.', needsYou: false, action: 'retry' },
  GITHUB_OUTAGE: { reason: 'GitHub is having an outage', remediation: 'GitHub is having an outage (githubstatus.com). Nothing is wrong with this PR and it was not sent back; approve again once GitHub recovers.', needsYou: false, action: 'retry' },
  TRANSIENT_NETWORK: { reason: 'Transient network error', remediation: 'Transient network or GitHub error. Retried automatically; check connectivity if it persists.', needsYou: false, action: 'retry' },
  TOOL_MISSING: { reason: 'Required tool is missing', remediation: "A required tool (gh/git/npm) is missing from the webhook's PATH. Install it or fix the launchd plist PATH.", needsYou: true, action: 'escalate' },
  PR_NOT_FOUND: { reason: 'GitHub has no such pull request', remediation: 'GitHub has no such pull request. It may have been closed or deleted, or the URL is wrong.', needsYou: true, action: 'escalate' },
  INVALID_REQUEST: { reason: 'Request did not contain a valid GitHub PR URL', remediation: 'The request did not contain a valid GitHub PR URL.', needsYou: true, action: 'escalate' },

  // Refusal codes: non-pattern failures decided by the gate (23 codes)
  OUT_OF_ORDER: { reason: 'merge another PR first', remediation: 'Another PR must merge first. See the blockedBy list on this ticket.', needsYou: false, action: 'escalate' },
  WRONG_BASE: { reason: 'rebase onto main', remediation: 'The PR is not based on main. Rebase onto main before approving.', needsYou: true, action: 'escalate' },
  SENT_BACK: { reason: 'sent back for rework', remediation: 'The PR was sent back to its ticket for rework.', needsYou: true, action: 'reengage' },
  CI_PENDING: { reason: 'checks still running', remediation: 'CI checks are still running. Approve again once they pass.', needsYou: false, action: 'escalate' },
  NO_MERGE_PROFILE: { reason: 'no merge profile configured', remediation: 'This project has no merge profile configured. Add one in the project settings.', needsYou: true, action: 'escalate' },
  MERGE_REFUSED: { reason: 'merge was refused', remediation: 'The merge was refused. See the ticket for details.', needsYou: true, action: 'escalate' },
  CI_FAILED: { reason: 'CI failed', remediation: 'CI failed. Fix the failing tests and approve again.', needsYou: true, action: 'reengage' },
  GATE_INFRA: { reason: 'infrastructure failed', remediation: 'The merge gate infrastructure failed (no test command, full disk, database locked). Retry once fixed.', needsYou: false, action: 'escalate' },
  MEMORY_PRESSURE: { reason: 'memory pressure', remediation: "The Mac's memory is under pressure, so the check waits. It starts by itself when pressure drops; nothing was stopped.", needsYou: false, action: 'escalate' },
  MAIN_RED: { reason: 'main was failing', remediation: 'main branch is failing tests. Approve again once main is green.', needsYou: false, action: 'escalate' },
  GATE_TESTS_FAILED: { reason: 'tests failed', remediation: 'Tests failed in the merge gate. Fix the failing tests and approve again.', needsYou: true, action: 'reengage' },
  VERSION_BUMP_FAILED: { reason: 'version bump failed', remediation: 'Version bump failed. Check the CHANGELOG format and ticket metadata.', needsYou: true, action: 'escalate' },
  REBASE_CONFLICT: { reason: 'rebase by hand needed', remediation: 'Needs a person to rebase by hand until #230 can resolve it automatically.', needsYou: true, action: 'escalate' },
  UNKNOWN: { reason: 'unclassified failure', remediation: 'Unclassified failure. See the evidence; this needs triage.', needsYou: true, action: 'escalate' },
  ENV_MISSING: { reason: 'missing tools', remediation: 'Run the webhook on a machine that has the toolchain, or install it here. The PR was not sent back for rework.', needsYou: true, action: 'escalate' },
  NO_UI_EVIDENCE: { reason: 'needed screenshots', remediation: 'This PR changes the UI but does not have screenshots. Add them to the PR.', needsYou: true, action: 'reengage' },
  IMAGES_UNPINNED: { reason: 'unpinned images', remediation: 'This PR has unpinned images. Pin them on GitHub or upload pinned ones.', needsYou: true, action: 'reengage' },
  IMAGES_STALE: { reason: 'screenshots are stale', remediation: 'The screenshots are stale. Update them to match the current UI.', needsYou: true, action: 'reengage' },
  UI_EVIDENCE_UNCHECKED: { reason: 'UI evidence unchecked', remediation: 'Mark the UI evidence as checked in the PR.', needsYou: true, action: 'escalate' },
  DECISIONS_UNCHECKED: { reason: 'decisions unchecked', remediation: 'Check the decisions needed for this PR.', needsYou: true, action: 'escalate' },
  DECISIONS_PENDING: { reason: 'decisions not answered', remediation: 'This PR has unanswered decisions. Answer them before approving.', needsYou: true, action: 'escalate' },
  DECISIONS_UNSTRUCTURED: { reason: 'decisions malformed', remediation: 'The Decisions section is not in the expected format. Fix it before approving.', needsYou: true, action: 'escalate' },
  ALREADY_MERGING: { reason: 'already merging', remediation: 'Nothing to do; its result shows when that merge finishes.', needsYou: false, action: 'wait' }
}

// Backward compat: REMEDIATION_BY_CODE for stage_strip.js (will be replaced by import from FAILURE_TABLE)
export const REMEDIATION_BY_CODE = Object.fromEntries(
  Object.entries(FAILURE_TABLE).map(([code, entry]) => [code, entry.remediation])
)

// Export the plain reason (just the message, no remediation) for dashboard displays
export function plainReason(code) {
  return FAILURE_TABLE[code]?.reason ?? 'unclassified failure'
}

// Lookup remediation text for a code, or null if unknown
export function remediationFor(code) {
  return FAILURE_TABLE[code]?.remediation ?? null
}

const EVIDENCE_MAX = 600

function textOf(error) {
  return [error?.message, error?.stderr, error?.stdout].filter(Boolean).map(String).join('\n')
}

// execFile's .message is "Command failed: <cmd>" -- the real reason is in stderr. Prefer the
// first non-empty stderr line; otherwise fall back to the message's first line.
function firstMeaningfulLine(error) {
  const fromStderr = String(error?.stderr ?? '').split('\n').map((l) => l.trim()).find(Boolean)
  const line = fromStderr || String(error?.message ?? error).split('\n')[0]
  return line.slice(0, 300)
}

export function classifyFailure({ stage, error }) {
  const text = textOf(error)
  const rule = RULES.find((r) => r.test.test(text))
  const code = rule ? rule.code : 'UNKNOWN'
  const entry = FAILURE_TABLE[code]
  return {
    code,
    stage,
    action: entry?.action || (rule ? rule.action : 'escalate'),
    retryable: rule ? rule.retryable : false,
    remediation: entry?.remediation || (rule ? rule.remediation : 'Unclassified failure. See the evidence; this needs triage.'),
    needsYou: entry?.needsYou ?? true,
    message: firstMeaningfulLine(error),
    evidence: text.slice(0, EVIDENCE_MAX)
  }
}

// An Error that carries the structured payload so the HTTP layer can return it as JSON
// while callers/tests that only look at .message still see the code and original text.
export class MergeFailure extends Error {
  constructor(payload) {
    super(`${payload.code} at ${payload.stage}: ${payload.message}`)
    this.name = 'MergeFailure'
    this.payload = payload
  }
}

const TEST_NAME_PATTERNS = [
  /^FAILED\s+(\S+)/,            // pytest short summary
  /^ERROR\s+(\S+)/,             // pytest collection/setup error
  /^\s*FAIL\s+(.+?)\s*$/,       // vitest
]
// XCTest: "Test Case '-[Suite testName]' failed" -> Suite/testName
const XCTEST_FAILED = /Test Case '-\[(\S+) (\S+)\]' failed/

// Signatures of the BUILD MACHINE or the project's test SETUP failing rather than the PR's code (a locked build
// database from two builds at once, a full disk, a lost network, a project with no test script yet). These must not send a good PR back for a pointless rebuild.
const GATE_INFRA = /did not finish within \d+ min|has no test command|missing script|database is locked|unable to attach db|no space left on device|could not resolve host|operation not permitted|resource temporarily unavailable|too many open files|cannot allocate memory/i

// Which part of the machine failed, in words the owner can act on (2026-10-28: Approve on #600 and #739 was refused with
// "the build machine or the project's test setup failed" while the gate knew the disk had 1.6 GB free). Each GATE_INFRA
// signature above has a sentence here; the code stays GATE_INFRA. `where` is the machine's label ("Mac mini"), derived
// from its device id at run time. The disk rule reads only the gate's own disk-check wording (rebaseAndRetest), so a
// test that prints "N GB free" is never taken for it. Returns { cause, next, needsYou } (one line each) or null when
// the failure is not the machine's. `needsYou` indicates if manual user action (vs. automatic retry) is needed.
const CAUSE_MAX = 200
const oneLine = (s, max = CAUSE_MAX) => String(s).replace(/\s+/g, ' ').trim().slice(0, max)
const DISK_CHECK = /^Disk check before rebasing[^\n]*\n+No space left on device for the check: (\d+(?:\.\d+)?) GB free, the gate needs (\d+(?:\.\d+)?) GB/i
const FIRST_AID_RAN = /^First aid ran first: ([^\n]+)$/m
const INFRA_CAUSES = [
  { test: /no space left on device/i, cause: (w) => `${w}'s disk filled up during the check (no space left on device)`, next: 'Free up space on this Mac, then approve again.', needsYou: true },
  { test: /has no test command|missing script/i, cause: () => 'This project has no test command yet, so the check could not run', next: 'Add a test script to the project, then approve again.', needsYou: true },
  { test: /database is locked|unable to attach db/i, cause: () => 'Two builds used the same build database at once (database is locked)', next: 'Approve again once the other build has finished.', needsYou: false },
  { test: /could not resolve host/i, cause: (w) => `${w} lost its network connection during the check (could not resolve host)`, next: 'Approve again once the network is back.', needsYou: false },
  { test: /operation not permitted/i, cause: () => 'macOS refused a file operation during the check (operation not permitted), usually a missing privacy permission', next: 'Check Full Disk Access for the webhook, then approve again.', needsYou: true },
  { test: /too many open files|resource temporarily unavailable/i, cause: (w) => `${w} ran out of processes or open files during the check`, next: 'Approve again once the machine is less busy.', needsYou: false },
  { test: /cannot allocate memory/i, cause: (w) => `${w} ran out of memory during the check`, next: 'Approve again once the machine is less busy.', needsYou: false }
]

export function infraCause(reason, { where } = {}) {
  const text = String(reason ?? '')
  const label = oneLine(where ?? '', 40)
  const w = label ? `The ${label}` : 'This Mac'
  const disk = text.match(DISK_CHECK)
  if (disk) {
    const aid = text.match(FIRST_AID_RAN)
    return {
      cause: oneLine(`${w}'s disk is nearly full (${disk[1]} GB free, the check needs ${disk[2]} GB)`),
      next: oneLine(`${aid ? `MARVIN cleared rebuildable files first (${aid[1].replace(/[.\s]+$/, '')}), and it was not enough. ` : ''}Free up space on this Mac, then approve again.`, 400),
      needsYou: true
    }
  }
  if (/^rebase onto main failed/i.test(text) || !GATE_INFRA.test(text)) return null
  const rule = INFRA_CAUSES.find((r) => r.test.test(text))
  if (!rule) return { cause: null, next: null, needsYou: false } // a GATE_INFRA signature with no sentence yet: assume infrastructure issue
  return { cause: oneLine(rule.cause(w)), next: rule.next, needsYou: rule.needsYou ?? false }
}

export function summarizeGateFailure(reason, { where } = {}) {
  const text = String(reason ?? '')
  const isRebase = /^rebase onto main failed/i.test(text)
  const code = isRebase ? 'REBASE_CONFLICT' : GATE_INFRA.test(text) ? 'GATE_INFRA' : 'GATE_TESTS_FAILED'
  const infra = code === 'GATE_INFRA' ? infraCause(text, { where }) : null
  const body = text.replace(/^[^\n]*:\s*\n+/, '') // drop the "…failed:" header line
  const lines = body.split('\n')

  const failingTests = []
  for (const line of lines) {
    const xc = line.match(XCTEST_FAILED)
    if (xc) {
      failingTests.push(`${xc[1]}/${xc[2]}`)
      continue
    }
    for (const re of TEST_NAME_PATTERNS) {
      const m = line.match(re)
      if (m) {
        failingTests.push(m[1].replace(/\s+-\s+.*$/, ''))
        break
      }
    }
  }
  const unique = [...new Set(failingTests)].slice(0, 15)
  const tail = lines.slice(-25).join('\n')

  const header = `**Merge gate: ${code}** (${isRebase ? 'rebasing onto main' : 'after rebasing onto main'})`
  const parts = [header]
  if (unique.length) {
    parts.push(`Failing tests (${unique.length}):\n${unique.map((t) => `- ${t}`).join('\n')}`)
  }
  parts.push(`Last output:\n\`\`\`\n${tail}\n\`\`\``)
  return { code, failingTests: unique, comment: parts.join('\n\n'), cause: infra?.cause ?? null, next: infra?.next ?? null, needsYou: infra?.needsYou ?? false }
}

// A refusal the gate decides itself (not a gh/git error to be pattern-matched): same shape as a
// classified failure so the HTTP layer and the dashboard treat it identically.
export function refusal(code, stage, message, remediation, action = 'escalate', needsYouOverride = null) {
  const entry = FAILURE_TABLE[code]
  const needsYou = needsYouOverride !== null ? needsYouOverride : (entry?.needsYou ?? true)
  return { code, stage, action, retryable: false, remediation, needsYou, message, evidence: '' }
}

export async function withRetry(fn, { classify, sleep = (ms) => new Promise((r) => setTimeout(r, ms)), retries = 3, baseMs = 2000 } = {}) {
  let attempts = 0
  for (;;) {
    attempts += 1
    try {
      return { value: await fn(), attempts }
    } catch (error) {
      error.attempts = attempts
      if (attempts > retries || !classify(error).retryable) throw error
      await sleep(baseMs * 2 ** (attempts - 1))
    }
  }
}

// HTTP response for a failed approve. Always 500 with a JSON body that keeps the legacy
// { merged:false, error } keys (older clients read those) and adds the structured fields.
export function failureResponse(error) {
  const payload = error instanceof MergeFailure ? error.payload : classifyFailure({ stage: 'merging', error })
  return {
    status: 500,
    body: { merged: false, error: `${payload.code} at ${payload.stage}: ${payload.message}`, ...payload }
  }
}
