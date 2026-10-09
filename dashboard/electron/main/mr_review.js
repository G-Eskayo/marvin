import { MARVIN_REPO, prKey, canMergeFromDashboard, repoFromPrUrl } from './mr_repos.js'
import { waitingOn, baseProblem } from './pr_order.js'
import { ciState } from '../../webhook-server/ci_status.js'
import { uiFiles, hasImage } from '../../webhook-server/ui_evidence.js'
import { parsePrImages } from './pr_images.js'
import { summarizeDecisions, vagueness } from '../../webhook-server/decisions.js'

// Reads open PRs and identifies which follow the MR pipeline's evidence
// schema (G-Eskayo/marvin#72, ADR 0024) -- one fixed, structured PR body
// format that every MR-pipeline PR uses whether it was raised
// autonomously (mr_raiser.py, G-Eskayo/marvin#4) or by a live/manual
// session. Detection is schema-based (are the section headers present),
// not the old exact-marker-string match, so manually-raised PRs that
// follow the schema are treated the same as pipeline-raised ones. Parses
// the metrics-comparison, test-results, and dev-environment-evidence
// sections back out for display, plus the linked ticket reference.
// Approving fires a webhook per the documented contract (see
// dashboard/webhook-server/README.md) rather than running `gh pr merge`
// itself -- G-Eskayo/marvin#11 is explicit that the dashboard is a
// trigger, not the thing that does the merge. Denying (ADR 0025) follows
// the same trigger-not-executor shape, via a second webhook endpoint.
export const EVIDENCE_HEADERS = {
  device: '## Device',
  metrics: '## Metrics Comparison',
  testResults: '## Test Results',
  devEvidence: '## Dev Environment Evidence',
  mutation: '## Mutation Score'
}

export function hasEvidenceSchema(body) {
  return (
    typeof body === 'string' &&
    body.includes(EVIDENCE_HEADERS.metrics) &&
    body.includes(EVIDENCE_HEADERS.testResults) &&
    body.includes(EVIDENCE_HEADERS.devEvidence)
  )
}

// Returns the section's own body text (everything after its "## " header
// up to the next "## " header or end of string), or '' if the header
// isn't present.
function extractSection(body, header) {
  const start = body.indexOf(header)
  if (start === -1) return ''
  const afterHeader = start + header.length
  const nextHeaderMatch = body.slice(afterHeader).match(/\n##\s/)
  const end = nextHeaderMatch ? afterHeader + nextHeaderMatch.index : body.length
  return body.slice(afterHeader, end).trim()
}

function parseMetricsSection(section) {
  const subsystemMatch = section.match(/\*\*Subsystem\*\*:\s*(.+)/)
  const verdictMatch = section.match(/\*\*Verdict\*\*:\s*(.+)/)

  const lines = section.split('\n')
  const headerIndex = lines.findIndex((line) => /^\|\s*Metric\s*\|/.test(line.trim()))
  const rows = []
  if (headerIndex !== -1) {
    // headerIndex + 1 is the "|---|---|..." separator row -- skip it too.
    for (let i = headerIndex + 2; i < lines.length; i++) {
      const line = lines[i].trim()
      if (!line.startsWith('|')) break
      const cells = line
        .split('|')
        .slice(1, -1)
        .map((c) => c.trim())
      if (cells.length === 5) {
        const [name, baseline, current, delta, direction] = cells
        rows.push({ name, baseline, current, delta, direction })
      }
    }
  }

  return {
    subsystem: subsystemMatch ? subsystemMatch[1].trim() : null,
    verdict: verdictMatch ? verdictMatch[1].trim() : null,
    metrics: rows
  }
}

function parseTestResultsSection(section) {
  if (!section) return null
  const suiteMatch = section.match(/\*\*Suite\*\*:\s*(.+)/)
  const passedMatch = section.match(/\*\*Passed\*\*:\s*(\d+)/)
  const failedMatch = section.match(/\*\*Failed\*\*:\s*(\d+)/)
  const totalMatch = section.match(/\*\*Total\*\*:\s*(\d+)/)
  if (!suiteMatch && !passedMatch && !failedMatch && !totalMatch) return null

  return {
    suite: suiteMatch ? suiteMatch[1].trim() : null,
    passed: passedMatch ? Number(passedMatch[1]) : null,
    failed: failedMatch ? Number(failedMatch[1]) : null,
    total: totalMatch ? Number(totalMatch[1]) : null
  }
}

function parseDevEvidenceSection(section) {
  if (!section) return null
  if (/^N\/A/i.test(section)) {
    return { na: true, reason: section.replace(/^N\/A\s*[—-]?\s*/i, '').trim() || null }
  }

  const imageMatch = section.match(/!\[[^\]]*\]\(([^)]+)\)/)
  const description = section.replace(/!\[[^\]]*\]\([^)]+\)/, '').trim()
  return {
    na: false,
    screenshot: imageMatch ? imageMatch[1].trim() : null,
    description: description || null
  }
}

function parseMutationSection(section) {
  if (!section) return null
  // Parse format like: "80% (4/5)" or "unknown (npx not found)" or "no mutable lines"
  const percentMatch = section.match(/(\d+(?:\.\d+)?)\%\s*\((\d+)\/(\d+)\)/)
  const unknownMatch = section.match(/unknown\s*\(([^)]+)\)/)
  const noMutableMatch = section.match(/no mutable lines/i)

  if (percentMatch) {
    return {
      status: 'ok',
      score: Number(percentMatch[1]),
      killed: Number(percentMatch[2]),
      total: Number(percentMatch[3])
    }
  } else if (unknownMatch) {
    return {
      status: 'unknown',
      reason: unknownMatch[1].trim()
    }
  } else if (noMutableMatch) {
    return {
      status: 'ok',
      score: 100,
      killed: 0,
      total: 0,
      reason: 'no mutable lines'
    }
  }

  return null
}

function parseDeviceSection(section) {
  if (!section) return null
  return section
}

export function parseTicketRef(body) {
  const match = body.match(/\b(?:Closes|Fixes|Resolves)\s+(?:[\w.-]+\/[\w.-]+)?#(\d+)/i)
  return match ? match[1] : null
}

function parseParentRef(body) {
  const match = body.match(/##\s*Parent\s*\n+\s*(?:[\w.-]+\/[\w.-]+)?#(\d+)/i)
  return match ? match[1] : null
}

// Fetches a ticket's own body (requirements/tasks) and, if it declares a
// "## Parent", that parent PRD's body too (design/architecture) -- live,
// via the injected ghIssueView, rather than duplicating either into the
// PR itself (G-Eskayo/marvin#72's schema deliberately links back to the
// ticket instead of restating it). Never throws: a missing/inaccessible
// ticket or parent comes back as `null` in the result rather than
// propagating the fetch error, so a stale or deleted reference doesn't
// break the detail view around it.
export async function fetchTicketContext(ticketRef, ghIssueView) {
  let ticket = null
  try {
    ticket = await ghIssueView(ticketRef)
  } catch {
    ticket = null
  }
  if (!ticket) {
    return { ticket: null, parent: null }
  }

  const parentRef = parseParentRef(ticket.body || '')
  let parent = null
  if (parentRef) {
    try {
      parent = await ghIssueView(parentRef)
    } catch {
      parent = null
    }
  }

  return { ticket, parent }
}

export function parseEvidence(body) {
  const metrics = parseMetricsSection(extractSection(body, EVIDENCE_HEADERS.metrics))
  return {
    ...metrics,
    device: parseDeviceSection(extractSection(body, EVIDENCE_HEADERS.device)),
    testResults: parseTestResultsSection(extractSection(body, EVIDENCE_HEADERS.testResults)),
    devEvidence: parseDevEvidenceSection(extractSection(body, EVIDENCE_HEADERS.devEvidence)),
    mutation: parseMutationSection(extractSection(body, EVIDENCE_HEADERS.mutation)),
    ticketRef: parseTicketRef(body)
  }
}

// Found live 2026-10-01: PR #119 had real, substantive content (its own
// written test-plan checklist, 107/107 passing) and sat open 30 days
// because the tab's only filter silently excluded anything that didn't
// follow the autonomous pipeline's exact evidence-schema template -- true
// of every manually-authored PR, not just malformed ones. A real PR
// disappearing with zero indication anywhere that it was excluded, let
// alone why, is worse than showing it with less structure. Every open PR
// now shows; `hasSchema` tells the UI whether to render the parsed
// evidence table or a plain fallback card, but approve/deny only ever
// needed the PR url (see approveMr/denyMr below), so both paths work for
// either kind.
// "repo#number" for every OPEN ticket in `issues` that was sent back for rework (label `needs-reengagement`).
export function sentBackKeys(repo, issues) {
  const keys = new Set()
  for (const i of issues || []) {
    if (i && i.state === 'OPEN' && (i.labels || []).some((l) => l.name === 'needs-reengagement')) keys.add(`${repo}#${i.number}`)
  }
  return keys
}

// Each PR marked with whether its ticket was sent back for rework, which is what merge order (pr_order.js) needs to skip
// it. Shared by the review list and the check run on the Approve click, so the two can never disagree (marvin #209).
export function markSentBack(prs, keys) {
  return prs.map((p) => {
    const ticket = parseTicketRef(p.body || '')
    return { ...p, repo: p.repo || MARVIN_REPO, sentBack: ticket !== null && keys.has(`${p.repo || MARVIN_REPO}#${ticket}`) }
  })
}

// The PR list to hand assertInOrder at Approve time. A failing lookup marks nothing sent back (fails closed on order).
export async function prsForOrderCheck(prs, sentBackTickets) {
  let keys = new Set()
  try {
    keys = await sentBackTickets([...new Set(prs.map((p) => p.repo || MARVIN_REPO))])
  } catch {
    keys = new Set()
  }
  return markSentBack(prs, keys)
}

// A UI change whose description shows no image (marvin #374): {files} for the card, or null. Only judged when the list
// carried the PR's files (the light list for the status dot doesn't), so a missing field never flags a PR.
function needsImages(pr, uiPathsFor) {
  if (!Array.isArray(pr.files)) return null
  let own = []
  try { own = uiPathsFor(pr.repo || MARVIN_REPO) || [] } catch { own = [] }
  const files = uiFiles(pr.files.map((f) => f?.path), own)
  return files.length && !hasImage(pr.body || '') ? { files } : null
}

export async function listPipelinePrs(listOpenPrs, { canMerge = canMergeFromDashboard, sentBackTickets = null, reworkStatus = null, rebaseStatus = null, closedTickets = null, autoMergeShadow = null, uiPathsFor = () => [] } = {}) {
  const prs = await listOpenPrs()
  // The webhook's post-merge rebase results, by PR url (#225). Best effort: without them a card just doesn't say.
  let rebased = {}
  if (rebaseStatus) {
    try {
      rebased = (await rebaseStatus()) || {}
    } catch {
      rebased = {}
    }
  }
  // Which tickets were sent back for rework ("repo#number" keys), asked once for the repos that have PRs. A failing
  // lookup never hides a PR: it just means nothing is flagged (the merge webhook refuses sent-back PRs on its own).
  let sentBackKeys = new Set()
  if (sentBackTickets) {
    try {
      sentBackKeys = await sentBackTickets([...new Set(prs.map((p) => p.repo || MARVIN_REPO))])
    } catch {
      sentBackKeys = new Set()
    }
  }
  // Auto-merge's shadow verdicts by PR url (#341), from the mini's merge server. Best effort.
  let shadow = {}
  if (autoMergeShadow) {
    try {
      shadow = ((await autoMergeShadow()) || {}).prs || {}
    } catch {
      shadow = {}
    }
  }
  // Tickets already closed ("repo#number"): a PR still open for one is probably a duplicate (#326). Best effort.
  let closedKeys = new Set()
  if (closedTickets) {
    try {
      closedKeys = await closedTickets([...new Set(prs.map((p) => p.repo || MARVIN_REPO))])
    } catch {
      closedKeys = new Set()
    }
  }
  // Where each sent-back ticket's rework stands (running, queued at position N, paused and why, held, needs a person).
  // Best effort: without it the card still says it was sent back.
  let rework = {}
  if (reworkStatus && sentBackKeys.size) {
    try {
      rework = (await reworkStatus()) || {}
    } catch {
      rework = {}
    }
  }
  // Each PR with the facts that decide whether it can be waited on (sent back for rework; conflicts), so merge order skips the
  // ones that cannot merge as they stand.
  const withState = markSentBack(prs, sentBackKeys)
  return prs.map((pr) => {
    const ticketRef = parseTicketRef(pr.body || '')
    const hasSchema = hasEvidenceSchema(pr.body)
    const evidence = hasSchema ? parseEvidence(pr.body) : null
    return {
      number: pr.number,
      title: pr.title,
      url: pr.url,
      repo: pr.repo || MARVIN_REPO,
      key: prKey(pr.repo || MARVIN_REPO, pr.number),
      canMerge: canMerge(pr.repo || MARVIN_REPO),
      conflicts: pr.mergeable === 'CONFLICTING',
      rebase: rebased[pr.url] || null,
      autoMerge: shadow[pr.url]?.current || null,
      checks: ciState(pr.statusCheckRollup),
      needsImages: needsImages(pr, uiPathsFor),
      // Choices the PR asks the owner to make (its Decisions section), and whether it asks in prose with nowhere to
      // answer (2026-10-09): either one holds Approve until it is answered or restated.
      decisions: summarizeDecisions(pr.body || ''),
      vague: vagueness(pr.body || ''),
      // Every image in the description (mock-ups, screenshots, frame strips), for the detail view's gallery.
      images: parsePrImages(pr.body || '', { repo: pr.repo || MARVIN_REPO, headRef: pr.headRefName }),
      baseProblem: baseProblem(prs.map((p) => ({ ...p, repo: p.repo || MARVIN_REPO })), { ...pr, repo: pr.repo || MARVIN_REPO }),
      waitingOn: waitingOn(withState, { ...pr, repo: pr.repo || MARVIN_REPO }),
      hasSchema,
      // The ticket was sent back for rework (marvin #129): approving would merge work that was just rejected.
      sentBack: ticketRef !== null && sentBackKeys.has(`${pr.repo || MARVIN_REPO}#${ticketRef}`),
      ticketRef,
      ticketClosed: ticketRef !== null && closedKeys.has(`${pr.repo || MARVIN_REPO}#${ticketRef}`),
      rework: ticketRef !== null && sentBackKeys.has(`${pr.repo || MARVIN_REPO}#${ticketRef}`) ? rework[`${pr.repo || MARVIN_REPO}#${ticketRef}`] || null : null,
      ticketNumber: evidence?.ticketRef ? Number(evidence.ticketRef) : null,
      evidence,
      // Full body, untruncated -- MrDetail.jsx needs the whole thing since
      // it's exactly the "drill in and actually read it" view; PrCard.jsx
      // truncates its own display slice for the compact list card.
      rawBody: hasSchema ? null : pr.body || ''
    }
  })
}

// Turns the webhook's structured failure body into a message that says what broke, where,
// and what happens next -- "Webhook call failed: 500" hid the real reason (2026-10-02).
function describeApproveFailure(status, body) {
  if (!body || !body.code) return `Webhook call failed: ${status}`
  const next =
    body.action === 'escalate'
      ? ' -- needs you'
      : body.action === 'retry'
        ? ` -- already retried ${body.attempts ?? '?'} times; try again shortly`
        : ' -- sent back to its ticket'
  return `${body.code} at ${body.stage}: ${body.message}${next}. ${body.remediation ?? ''}`.trim()
}

export async function approveMr(prUrl, webhookUrl, post) {
  const response = await post(webhookUrl, { pr_url: prUrl })
  if (!response.ok) {
    let body = null
    try {
      body = await response.json()
    } catch {
      // not JSON (or no body): fall back to the bare status below
    }
    const error = new Error(describeApproveFailure(response.status, body))
    if (body && body.code) error.payload = body
    throw error
  }
  // A 200 covers both an actual merge and G-Eskayo/marvin#91's merge-time
  // gate routing to re-engagement instead -- callers need the real body
  // (merged/reengaged/reason) to tell those apart, not just "it worked."
  return response.json()
}

// ADR 0025: Deny opens a structured-feedback modal with two terminal
// actions -- "send_feedback" (comment + release claim + tag for the
// future review/debug/improve pipeline) or "drop" (close PR + ticket,
// release claim, no re-engagement expected). Same webhook-trigger shape
// as approveMr, one endpoint, action carried in the body.
export async function denyMr({ prUrl, ticketNumber, action, reasons, comment }, webhookUrl, post) {
  const response = await post(webhookUrl, {
    action,
    pr_url: prUrl,
    ticket_number: ticketNumber,
    reasons,
    comment
  })
  if (!response.ok) {
    throw new Error(`Webhook call failed: ${response.status}`)
  }
  return response
}

// The way out when a PR is shown as "sent back" but should not be (the label was applied by a mistake or the rework
// already landed). Removes `needs-reengagement` from the PR's own ticket, unless a rework is actually running (the
// ticket is claimed), where clearing it would race the rebuild.
export async function clearSentBackLabel(prUrl, exec) {
  const repo = repoFromPrUrl(prUrl)
  const { stdout: prOut } = await exec('gh', ['pr', 'view', prUrl, '--json', 'body'])
  const ticket = parseTicketRef(JSON.parse(prOut).body || '')
  if (!ticket || !repo) return { cleared: false, reason: 'This PR has no ticket to clear.' }
  const { stdout: issueOut } = await exec('gh', ['issue', 'view', ticket, '--repo', repo, '--json', 'labels'])
  const labels = (JSON.parse(issueOut).labels || []).map((l) => l.name)
  if (!labels.includes('needs-reengagement')) return { cleared: false, reason: 'Its ticket is not sent back (the label is already gone).' }
  const claim = labels.find((l) => l.startsWith('claimed:'))
  if (claim) return { cleared: false, reason: `A rework is running (claimed by ${claim.slice('claimed:'.length)}). Wait for it to finish.` }
  await exec('gh', ['issue', 'edit', ticket, '--repo', repo, '--remove-label', 'needs-reengagement'])
  await exec('gh', ['issue', 'comment', ticket, '--repo', repo, '--body',
    `The "sent back" label was cleared from the dashboard: this PR (${prUrl}) is judged fine as it stands, so it can be reviewed and merged.`])
  return { cleared: true }
}
