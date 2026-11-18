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
    label: 'GitHub credential invalid',
    remediation: 'GitHub rejected the credential. Fix ~/.claude/.gh-token on the machine running the webhook (the Health tab shows auth:gh per machine).',
    needsYou: true },
  { code: 'NOT_MERGEABLE', action: 'reengage', retryable: false,
    test: /not mergeable|merge conflict|conflicts? must be resolved|cannot be merged/i,
    label: 'PR has conflicts',
    remediation: 'The PR conflicts with main. It was sent back to its ticket for rework.',
    needsYou: false },
  // GitHub will not merge a draft. The gate marks an owner-approved draft ready first (readyIfDraft in merge.js);
  // this catches one that slipped through, so it is named instead of UNKNOWN (clarity-captions #77/#78, 2026-10-09).
  { code: 'PR_DRAFT', action: 'escalate', retryable: false,
    test: /is still a draft|pull request is a draft|draft pull request/i,
    label: 'PR is still a draft',
    remediation: 'The PR is a draft. Mark it "Ready for review" on GitHub, then approve again. The PR was not sent back.',
    needsYou: true },
  { code: 'BRANCH_PROTECTION', action: 'escalate', retryable: false,
    test: /protected branch|required status check|required review|branch protection|gh006|gh013/i,
    label: 'Branch protection blocked merge',
    remediation: 'Branch protection blocked the merge. Satisfy the required checks/reviews, or adjust the rule.',
    needsYou: true },
  // GitHub refuses a merge when the base branch moved between it checking and merging (two merges close
  // together). Nothing is wrong with the PR; trying again, once main has settled, is the right response.
  { code: 'BASE_MOVED', action: 'retry', retryable: true,
    test: /base branch was modified|try the merge again/i,
    label: 'Main moved during merge',
    remediation: 'main moved while this merged. Retried automatically; if it keeps failing, another merge is racing it.',
    needsYou: false },
  { code: 'RATE_LIMITED', action: 'retry', retryable: true,
    test: /rate limit|secondary rate|abuse detection/i,
    label: 'GitHub rate limit',
    remediation: 'GitHub rate limit. Retried automatically with backoff; try again shortly if it persists.',
    needsYou: false },
  // GitHub itself failing (an incident, not our network): its own 5xx answers. Seen 2026-10-07 when a rebase push
  // died with "remote: Internal Server Error" after a full retest. The PR is fine; waiting and retrying is the answer.
  { code: 'GITHUB_OUTAGE', action: 'retry', retryable: true,
    test: /internal server error|http 500|returned error: 50[0-4]/i,
    label: 'GitHub is down',
    remediation: 'GitHub is having an outage (githubstatus.com). Nothing is wrong with this PR and it was not sent back; approve again once GitHub recovers.',
    needsYou: false },
  { code: 'TRANSIENT_NETWORK', action: 'retry', retryable: true,
    test: /econnreset|etimedout|enotfound|econnrefused|eai_again|socket hang up|network|timed out|http 50[234]|bad gateway|service unavailable|gateway time-?out/i,
    label: 'Transient network error',
    remediation: 'Transient network or GitHub error. Retried automatically; check connectivity if it persists.',
    needsYou: false },
  { code: 'TOOL_MISSING', action: 'escalate', retryable: false,
    test: /enoent|command not found|no such file or directory.*(gh|git|npm|npx)/i,
    label: 'Required tool missing',
    remediation: "A required tool (gh/git/npm) is missing from the webhook's PATH. Install it or fix the launchd plist PATH.",
    needsYou: true },
  { code: 'PR_NOT_FOUND', action: 'escalate', retryable: false,
    test: /could not resolve to a pullrequest|pull request not found|no pull requests? found/i,
    label: 'PR not found',
    remediation: 'GitHub has no such pull request. It may have been closed or deleted, or the URL is wrong.',
    needsYou: true },
  { code: 'INVALID_REQUEST', action: 'escalate', retryable: false,
    test: /not a github pr url/i,
    label: 'Invalid PR URL',
    remediation: 'The request did not contain a valid GitHub PR URL.',
    needsYou: true }
]

// Consolidated code info: labels, remediations, and whether this needs the owner to act.
export const CODE_INFO = Object.fromEntries(
  [
    ...RULES,
    // From inline refusal() calls in merge.js and decisions.js:
    { code: 'OUT_OF_ORDER', label: 'merge another PR first', remediation: 'Another PR must merge first. See the blockedBy list on this ticket.', needsYou: false },
    { code: 'WRONG_BASE', label: 'wrong base branch', remediation: 'The PR is not based on main. Rebase onto main before approving.', needsYou: true },
    { code: 'SENT_BACK', label: 'sent back for rework', remediation: 'The PR was sent back to its ticket for rework.', needsYou: false },
    { code: 'CI_PENDING', label: 'checks still running', remediation: 'CI checks are still running. Approve again once they pass.', needsYou: false },
    { code: 'NO_MERGE_PROFILE', label: 'this project cannot merge from the dashboard', remediation: 'This project has no merge profile configured. Add one in the project settings.', needsYou: true },
    { code: 'MERGE_REFUSED', label: 'GitHub refused the merge', remediation: 'The merge was refused. See the ticket for details.', needsYou: false },
    { code: 'CI_FAILED', label: 'GitHub checks failed', remediation: 'CI failed. Fix the failing tests and approve again.', needsYou: true },
    { code: 'GATE_INFRA', label: 'the build machine failed', remediation: 'The merge gate infrastructure failed (no test command, full disk, database locked). Retry once fixed.', needsYou: true },
    { code: 'MEMORY_PRESSURE', label: 'waiting for memory', remediation: 'The Mac\'s memory is under pressure, so the check waits. It starts by itself when pressure drops; nothing was stopped.', needsYou: false },
    { code: 'MAIN_RED', label: 'main was failing', remediation: 'main branch is failing tests. Approve again once main is green.', needsYou: false },
    { code: 'GATE_TESTS_FAILED', label: 'tests failed', remediation: 'Tests failed in the merge gate. Fix the failing tests and approve again.', needsYou: true },
    { code: 'VERSION_BUMP_FAILED', label: 'version bump failed', remediation: 'Version bump failed. Check the CHANGELOG format and ticket metadata.', needsYou: true },
    { code: 'REBASE_CONFLICT', label: 'conflicts after rebase', remediation: 'Needs a person to rebase by hand until #230 can resolve it automatically.', needsYou: true },
    { code: 'NO_UI_EVIDENCE', label: 'needed screenshots', remediation: 'Add images of the changed screens to the PR description.', needsYou: true },
    { code: 'UI_EVIDENCE_UNCHECKED', label: 'images not verified', remediation: 'The images exist but failed verification. Check that they show the current state and are clearly linked.', needsYou: true },
    { code: 'IMAGES_UNPINNED', label: 'images unpinned', remediation: 'Link the images by the commit they were taken at.', needsYou: true },
    { code: 'DECISIONS_PENDING', label: 'decisions not answered', remediation: 'Answer the required decisions in the PR.', needsYou: true },
    { code: 'DECISIONS_UNCHECKED', label: 'decisions not valid', remediation: 'The decisions section failed validation. Check the structure and ensure all required fields are present.', needsYou: true },
    { code: 'DECISIONS_UNSTRUCTURED', label: 'decisions improperly formatted', remediation: 'Use the Decisions section format with buttons and options, not prose.', needsYou: true },
    { code: 'ENV_MISSING', label: 'environment not configured', remediation: 'A required environment variable or configuration is missing. Check the setup.', needsYou: true },
    { code: 'ALREADY_MERGING', label: 'already merging on this machine', remediation: 'This PR is already merging on another machine. Wait for it to finish.', needsYou: false },
    { code: 'IMAGES_STALE', label: 'images are stale', remediation: 'Re-pin the images to the latest commit.', needsYou: true },
    { code: 'UNKNOWN', label: 'unclassified failure', remediation: 'Unclassified failure. See the evidence; this needs triage.', needsYou: true }
  ].map((r) => [r.code, { label: r.label, remediation: r.remediation, needsYou: r.needsYou }])
)

// Built from CODE_INFO for backward compatibility: just the remediation text by code.
export const REMEDIATION_BY_CODE = Object.fromEntries(
  Object.entries(CODE_INFO).map(([code, info]) => [code, info.remediation])
)

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
  return {
    code: rule ? rule.code : 'UNKNOWN',
    stage,
    action: rule ? rule.action : 'escalate',
    retryable: rule ? rule.retryable : false,
    remediation: rule ? rule.remediation : 'Unclassified failure. See the evidence; this needs triage.',
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
// test that prints "N GB free" is never taken for it. Returns { cause, next } (one line each) or null when the failure
// is not the machine's.
const CAUSE_MAX = 200
const oneLine = (s, max = CAUSE_MAX) => String(s).replace(/\s+/g, ' ').trim().slice(0, max)
const DISK_CHECK = /^Disk check before rebasing[^\n]*\n+No space left on device for the check: (\d+(?:\.\d+)?) GB free, the gate needs (\d+(?:\.\d+)?) GB/i
const FIRST_AID_RAN = /^First aid ran first: ([^\n]+)$/m
const INFRA_CAUSES = [
  { test: /no space left on device/i, cause: (w) => `${w}'s disk filled up during the check (no space left on device)`, next: 'Free up space on this Mac, then approve again.' },
  { test: /has no test command|missing script/i, cause: () => 'This project has no test command yet, so the check could not run', next: 'Add a test script to the project, then approve again.' },
  { test: /database is locked|unable to attach db/i, cause: () => 'Two builds used the same build database at once (database is locked)', next: 'Approve again once the other build has finished.' },
  { test: /could not resolve host/i, cause: (w) => `${w} lost its network connection during the check (could not resolve host)`, next: 'Approve again once the network is back.' },
  { test: /operation not permitted/i, cause: () => 'macOS refused a file operation during the check (operation not permitted), usually a missing privacy permission', next: 'Check Full Disk Access for the webhook, then approve again.' },
  { test: /too many open files|resource temporarily unavailable/i, cause: (w) => `${w} ran out of processes or open files during the check`, next: 'Approve again once the machine is less busy.' },
  { test: /cannot allocate memory/i, cause: (w) => `${w} ran out of memory during the check`, next: 'Approve again once the machine is less busy.' }
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
      next: oneLine(`${aid ? `MARVIN cleared rebuildable files first (${aid[1].replace(/[.\s]+$/, '')}), and it was not enough. ` : ''}Free up space on this Mac, then approve again.`, 400)
    }
  }
  if (/^rebase onto main failed/i.test(text) || !GATE_INFRA.test(text)) return null
  const rule = INFRA_CAUSES.find((r) => r.test.test(text))
  if (!rule) return { cause: null, next: null } // a GATE_INFRA signature with no sentence yet (e.g. the time limit): the caller words it
  return { cause: oneLine(rule.cause(w)), next: rule.next }
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
  return { code, failingTests: unique, comment: parts.join('\n\n'), cause: infra?.cause ?? null, next: infra?.next ?? null }
}

// A refusal the gate decides itself (not a gh/git error to be pattern-matched): same shape as a
// classified failure so the HTTP layer and the dashboard treat it identically.
export function refusal(code, stage, message, remediation, action = 'escalate') {
  return { code, stage, action, retryable: false, remediation, message, evidence: '' }
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
