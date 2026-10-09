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

export const RULES = [
  { code: 'GH_AUTH_INVALID', action: 'escalate', retryable: false,
    test: /bad credentials|http 401|authentication failed|could not read username|requires authentication|token.*(invalid|expired)|invalid.*token/i,
    remediation: 'GitHub rejected the credential. Fix ~/.claude/.gh-token on the machine running the webhook (the Health tab shows auth:gh per machine).' },
  { code: 'NOT_MERGEABLE', action: 'reengage', retryable: false,
    test: /not mergeable|merge conflict|conflicts? must be resolved|cannot be merged/i,
    remediation: 'The PR conflicts with main. It was sent back to its ticket for rework.' },
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

export function summarizeGateFailure(reason) {
  const text = String(reason ?? '')
  const isRebase = /^rebase onto main failed/i.test(text)
  const code = isRebase ? 'REBASE_CONFLICT' : GATE_INFRA.test(text) ? 'GATE_INFRA' : 'GATE_TESTS_FAILED'
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
  return { code, failingTests: unique, comment: parts.join('\n\n') }
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

// Remediation messages derived from RULES + all refusal() call sites, so dashboard and webhook share one source.
export const REMEDIATION_BY_CODE = Object.fromEntries(
  RULES.filter((r) => r.remediation).map((r) => [r.code, r.remediation])
)
