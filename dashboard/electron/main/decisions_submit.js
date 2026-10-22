import { mkdtemp, writeFile, rm } from 'fs/promises'
import { tmpdir } from 'os'
import { join } from 'path'
import { parseDecisions, applyAnswers, pendingDecisions, decisionsComment } from '../../webhook-server/decisions.js'

// Submitting the owner's answers to a Decisions section (PR or ticket), from the dashboard. The description is the
// source of truth: it is re-read fresh, the answers are written into it (ticked boxes, Answer/Note lines), and only
// after that edit lands is a "Decisions from the owner" comment posted as the record. A failed comment never undoes
// the answers; the result says what happened.

const REPO_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/
// Matches lib/ticket_policy.py: HOLD_LABELS
const HOLD_LABELS = new Set(['pinned', 'hold', 'held'])

async function writeTempJson(value) {
  const dir = await mkdtemp(join(tmpdir(), 'marvin-decisions-'))
  const file = join(dir, 'body.json')
  await writeFile(file, JSON.stringify(value))
  return { file, cleanup: () => rm(dir, { recursive: true, force: true }) }
}

// Checks the answers against the questions, so a stale screen can't tick an option that no longer exists.
export function validateAnswers(parsed, answers) {
  if (!answers || typeof answers !== 'object' || Array.isArray(answers)) throw new Error('no answers to submit')
  const byId = Object.fromEntries(parsed.questions.map((q) => [q.id, q]))
  for (const [id, a] of Object.entries(answers)) {
    const q = byId[id]
    if (!q) throw new Error(`"${id}" is not a question in this description (it may have changed: reload)`)
    if (q.kind === 'text') {
      if (a.choices?.length) throw new Error(`"${id}" takes a written answer, not options`)
      continue
    }
    const labels = new Set(q.options.map((o) => o.label))
    for (const c of a.choices || []) if (!labels.has(c)) throw new Error(`"${c}" is not an option of "${id}" (reload: the options changed)`)
    if (q.kind === 'single' && (a.choices || []).length > 1) throw new Error(`"${id}" takes one answer`)
  }
}

// `gh api --include` prints the status line and headers, a blank line, then the body. GitHub's reply to the PATCH is
// the issue as stored: that, not what was sent, is what the screen shows (local-first actions).
export function parseIncluded(stdout) {
  const text = String(stdout || '')
  if (!/^HTTP\/[\d.]+ \d{3}/.test(text)) {
    try { return { etag: null, json: JSON.parse(text) } } catch { return { etag: null, json: null } }
  }
  const split = text.search(/\r?\n\r?\n/)
  const head = split < 0 ? text : text.slice(0, split)
  const rest = split < 0 ? '' : text.slice(split).replace(/^\r?\n\r?\n/, '')
  const etag = (head.match(/^etag:\s*(.+?)\s*$/im) || [])[1] || null
  try { return { etag, json: JSON.parse(rest) } } catch { return { etag, json: null } }
}

// The record of the answers (a comment) and, for a ticket that was waiting on them, its move to ready-for-agent. The two
// are independent, so they run side by side; neither failing undoes the answers.
async function recordAnswers({ repo, n, issue, parsed, answers, pending }, exec) {
  const out = { commentUrl: null, commentError: null, labelsChanged: false }
  const comment = exec('gh', ['api', `repos/${repo}/issues/${n}/comments`, '-f', `body=${decisionsComment(parsed, answers)}`, '--jq', '.html_url'])
    .then(({ stdout: url }) => { out.commentUrl = String(url).trim() || null })
    .catch((error) => { out.commentError = `answers saved in the description, but the record comment failed: ${String(error?.stderr || error?.message || error).split('\n')[0]}` })
  // A ticket waiting on these decisions (needs-info) is ready for an agent once every required one is answered.
  // Skip the move if the ticket is held by a person.
  const labels = (issue.labels || []).map((l) => (typeof l === 'string' ? l : l.name))
  const labelSet = new Set(labels)
  const isHeld = Array.from(HOLD_LABELS).some(h => labelSet.has(h))
  const move = !issue.pull_request && !pending.length && labels.includes('needs-info') && !isHeld
    ? exec('gh', ['issue', 'edit', String(n), '--repo', repo, '--remove-label', 'needs-info', '--add-label', 'ready-for-agent'])
      .then(() => { out.labelsChanged = true })
      .catch((error) => { out.labelError = `answers saved, but moving the ticket to ready-for-agent failed: ${String(error?.stderr || error?.message || error).split('\n')[0]}` })
    : isHeld && !issue.pull_request && !pending.length && labels.includes('needs-info')
      ? Promise.resolve().then(() => { out.heldNote = 'answers saved, but the ticket is held: it will not move to ready-for-agent until the hold label is removed' })
      : null
  await Promise.all([comment, move])
  return out
}

// background: return as soon as GitHub has accepted the edit (with GitHub's own body), and hand the record comment and
// label change back as `recorded`, a promise that never rejects. Without it, everything is awaited as before.
export async function submitDecisions({ repo, number, answers }, { exec, writeTemp = writeTempJson, background = false }) {
  if (!REPO_RE.test(String(repo || ''))) throw new Error(`not a repository: ${repo}`)
  const n = Number(number)
  if (!Number.isInteger(n) || n <= 0) throw new Error(`not an issue or PR number: ${number}`)

  const { stdout } = await exec('gh', ['api', `repos/${repo}/issues/${n}`])
  const issue = JSON.parse(stdout)
  const body = issue.body || ''
  const parsed = parseDecisions(body)
  if (!parsed.present) throw new Error('this description has no Decisions section (it may have changed: reload)')
  validateAnswers(parsed, answers)

  const updated = applyAnswers(body, answers)
  if (updated === body) return { ok: true, unchanged: true, pending: pendingDecisions(parsed), commentUrl: null, body, etag: null, disagreed: false }

  const tmp = await writeTemp({ body: updated })
  let answer
  try {
    answer = parseIncluded((await exec('gh', ['api', '-X', 'PATCH', `repos/${repo}/issues/${n}`, '--input', tmp.file, '--include'])).stdout)
  } finally {
    await tmp.cleanup()
  }
  const stored = typeof answer.json?.body === 'string' ? answer.json.body : updated
  const pending = pendingDecisions(parseDecisions(stored))
  const result = { ok: true, unchanged: false, pending, body: stored, sent: updated, etag: answer.etag, disagreed: stored !== updated, commentUrl: null, commentError: null, labelsChanged: false }

  // GitHub kept something other than what was sent: no comment may claim answers the description does not hold.
  const recorded = result.disagreed
    ? Promise.resolve({ commentUrl: null, commentError: null, labelsChanged: false, skipped: 'GitHub did not store the answers as sent' })
    : recordAnswers({ repo, n, issue, parsed, answers, pending }, exec)
  if (background) return { ...result, recorded }
  return { ...result, ...(await recorded) }
}

export const OPTIONS_REQUEST = (reasons = []) =>
  'The owner can\'t approve this yet: it asks for choices but gives no options to answer' +
  (reasons.length ? ` (${reasons.join('; ')})` : '') + '.\n\n' +
  'Restate every question as a Decisions section (format: `docs/agents/decisions-format.md` in the marvin repo):\n\n' +
  '```\n## Decisions\n<!-- marvin:decisions -->\n### some-id: The question?\n- [ ] First option\n- [ ] Second option\n' +
  '### other-id: Several allowed? (pick any) (optional)\n- [ ] ...\n### words: Anything to add? (text) (optional)\n```\n\n' +
  'Then the owner picks from buttons in the dashboard and Approve unlocks once the required ones are answered.'

// "Send back for options": a pipeline PR goes back to its ticket through the normal deny path with this reason; a
// hand-made PR gets the same request as a comment.
export async function sendBackForOptions({ prUrl, ticketNumber, reasons }, { exec, deny }) {
  const comment = OPTIONS_REQUEST(reasons || [])
  if (ticketNumber) {
    await deny({ prUrl, ticketNumber, action: 'feedback', reasons: ['Design/requirements mismatch'], comment })
    return { sentBack: true, commented: true }
  }
  await exec('gh', ['pr', 'comment', prUrl, '--body', comment])
  return { sentBack: false, commented: true }
}
