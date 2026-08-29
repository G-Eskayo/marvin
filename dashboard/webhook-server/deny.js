import { execFile } from 'child_process'
import { promisify } from 'util'

const execFileAsync = promisify(execFile)
const REPO = 'G-Eskayo/marvin'
const REENGAGEMENT_LABEL = 'needs-reengagement'

function assertGithubPrUrl(prUrl) {
  if (typeof prUrl !== 'string' || !prUrl.startsWith('https://github.com/')) {
    throw new Error(`Not a GitHub PR URL: ${prUrl}`)
  }
}

// ADR 0025's structured feedback: reason categories plus an optional
// free-text comment, folded into one comment body posted to both the PR
// and its originating ticket.
export function formatFeedback(reasons = [], comment = '') {
  const lines = ['Denied by dashboard review.']
  if (reasons.length > 0) {
    lines.push('', 'Reasons:', ...reasons.map((reason) => `- ${reason}`))
  }
  if (comment && comment.trim()) {
    lines.push('', comment.trim())
  }
  return lines.join('\n')
}

// Mirrors lib/ticket_claim.py's release() -- claim state lives entirely as
// a claimed:<machine_id> GitHub label, and this webhook doesn't know which
// machine claimed a given ticket, so it removes whatever claimed:* labels
// are actually present rather than guessing a machine id.
async function releaseClaim(ticketNumber, exec) {
  if (!ticketNumber) return
  const { stdout } = await exec('gh', ['issue', 'view', String(ticketNumber), '--repo', REPO, '--json', 'labels'])
  const claimLabels = JSON.parse(stdout).labels.map((label) => label.name).filter((name) => name.startsWith('claimed:'))
  for (const label of claimLabels) {
    await exec('gh', ['issue', 'edit', String(ticketNumber), '--repo', REPO, '--remove-label', label])
  }
}

// Same "create the label on first use" fallback as
// lib/ticket_claim.py's _default_add_claim_label -- this label doesn't
// exist on the repo yet since the pipeline that will consume it
// (review/debug/improve) isn't built yet (ADR 0025).
async function tagForReengagement(ticketNumber, exec) {
  if (!ticketNumber) return
  try {
    await exec('gh', ['issue', 'edit', String(ticketNumber), '--repo', REPO, '--add-label', REENGAGEMENT_LABEL])
  } catch (err) {
    if (!String(err.message || err).toLowerCase().includes('not found')) throw err
    await exec('gh', ['label', 'create', REENGAGEMENT_LABEL, '--repo', REPO])
    await exec('gh', ['issue', 'edit', String(ticketNumber), '--repo', REPO, '--add-label', REENGAGEMENT_LABEL])
  }
}

export async function sendFeedback({ prUrl, ticketNumber, reasons, comment }, exec = execFileAsync) {
  assertGithubPrUrl(prUrl)
  const feedback = formatFeedback(reasons, comment)
  await exec('gh', ['pr', 'comment', prUrl, '--body', feedback])
  if (ticketNumber) {
    await exec('gh', ['issue', 'comment', String(ticketNumber), '--repo', REPO, '--body', feedback])
  }
  await releaseClaim(ticketNumber, exec)
  await tagForReengagement(ticketNumber, exec)
}

export async function dropEntirely({ prUrl, ticketNumber }, exec = execFileAsync) {
  assertGithubPrUrl(prUrl)
  await exec('gh', ['pr', 'close', prUrl])
  if (ticketNumber) {
    await exec('gh', ['issue', 'close', String(ticketNumber), '--repo', REPO])
  }
  await releaseClaim(ticketNumber, exec)
}
