import { mkdtemp, writeFile, rm } from 'fs/promises'
import { tmpdir } from 'os'
import { join } from 'path'
import { parseDecisions, applyAnswers, pendingDecisions, decisionsComment } from '../../webhook-server/decisions.js'

// Submitting the owner's answers to a Decisions section (PR or ticket), from the dashboard. The description is the
// source of truth: it is re-read fresh, the answers are written into it (ticked boxes, Answer/Note lines), and only
// after that edit lands is a "Decisions from the owner" comment posted as the record. A failed comment never undoes
// the answers; the result says what happened.

const REPO_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/

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

export async function submitDecisions({ repo, number, answers }, { exec, writeTemp = writeTempJson }) {
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
  const pending = pendingDecisions(parseDecisions(updated))
  if (updated === body) return { ok: true, unchanged: true, pending, commentUrl: null }

  const tmp = await writeTemp({ body: updated })
  try {
    await exec('gh', ['api', '-X', 'PATCH', `repos/${repo}/issues/${n}`, '--input', tmp.file])
  } finally {
    await tmp.cleanup()
  }

  const result = { ok: true, unchanged: false, pending, commentUrl: null, commentError: null, labelsChanged: false }
  try {
    const { stdout: url } = await exec('gh', ['api', `repos/${repo}/issues/${n}/comments`, '-f', `body=${decisionsComment(parsed, answers)}`, '--jq', '.html_url'])
    result.commentUrl = String(url).trim() || null
  } catch (error) {
    result.commentError = `answers saved in the description, but the record comment failed: ${String(error?.stderr || error?.message || error).split('\n')[0]}`
  }

  // A ticket waiting on these decisions (needs-info) is ready for an agent once every required one is answered.
  const labels = (issue.labels || []).map((l) => (typeof l === 'string' ? l : l.name))
  if (!issue.pull_request && !pending.length && labels.includes('needs-info')) {
    try {
      await exec('gh', ['issue', 'edit', String(n), '--repo', repo, '--remove-label', 'needs-info', '--add-label', 'ready-for-agent'])
      result.labelsChanged = true
    } catch (error) {
      result.labelError = `answers saved, but moving the ticket to ready-for-agent failed: ${String(error?.stderr || error?.message || error).split('\n')[0]}`
    }
  }
  return result
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
