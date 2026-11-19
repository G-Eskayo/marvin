import { MergeFailure, refusal } from './failure.js'
import { summarizeDecisions, vagueness } from './decisions.js'
import { promisify } from 'util'
import { execFile } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const VENV_PYTHON = path.resolve(__dirname, '..', '..', 'venv', 'bin', 'python')
const OWNER_DECISIONS_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'owner_decisions.py')
const execFileAsync = promisify(execFile)

// The merge server refuses a PR whose own description still has open required decisions, or that asks for a choice in
// prose with nowhere to answer it. Fails closed, like the image check: a refused Approve costs a click.
export async function assertDecisions(prUrl, exec) {
  let body
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'body'])
    body = JSON.parse(stdout).body || ''
  } catch (error) {
    const reason = String(error?.stderr || error?.message || error).split('\n')[0].slice(0, 200)
    throw new MergeFailure(refusal('DECISIONS_UNCHECKED', 'request',
      `couldn't check this PR's decisions (${reason})`,
      'Approve again in a moment. A PR that asks you to choose something merges only once you have answered.'))
  }
  const summary = summarizeDecisions(body)
  if (summary) {
    if (summary.pending.length) {
      throw new MergeFailure(refusal('DECISIONS_PENDING', 'request',
        `this PR still has decisions to answer: ${summary.pending.join(', ')}`,
        'Answer them in the Decisions section of the PR (dashboard) and submit, then approve. The PR was not sent back.'))
    }
    return
  }
  const vague = vagueness(body)
  if (vague) {
    throw new MergeFailure(refusal('DECISIONS_UNSTRUCTURED', 'request',
      `this PR asks you to choose something but gives no options to answer (${vague.reasons[0]})`,
      'Send it back for options: the author restates the questions as a Decisions section (docs/agents/decisions-format.md). The PR was not changed.'))
  }
}

// The merge queue's recheck for merged PRs (marvin#231): when approving a PR, file its owner-decisions follow-up
// if its owner's answers aren't built yet. The owner_decisions.py request command files it now, without grace hours.
export async function assertDecisionsBuilt(prUrl, execFn) {
  const m = /\/(\w[\w.-]*\/[\w.-]*)\/pull\/(\d+)$/.exec(prUrl)
  if (!m) return
  const [, repo, number] = [m[0], m[1], m[2]]
  let result
  try {
    // Use the provided exec function (from merge.js) to call the Python script.
    // If no exec is provided, use execFileAsync as a fallback.
    const execToUse = execFn || (async (cmd, args) => execFileAsync(cmd, args, { timeout: 60000 }))
    const { stdout } = await execToUse(VENV_PYTHON, [OWNER_DECISIONS_SCRIPT, 'request', '--repo', repo, '--pr', number])
    result = stdout.trim()
  } catch (error) {
    // Script execution failed; check the error message.
    const stderr = String(error?.stderr || '').trim().split('\n')[0]
    const message = String(error?.message || error).split('\n')[0]
    const fullError = stderr || message || ''
    if (fullError.includes('nothing to request') || fullError.includes('no owner Decisions')) return
    if (fullError.includes('skipped') || fullError.includes('could not')) {
      throw new MergeFailure(refusal('DECISIONS_UNCHECKED', 'later',
        `couldn't check whether this PR's decisions are built (${fullError.slice(0, 100)})`,
        'Approve again in a moment. The merge server will retry the check.'))
    }
    // Other errors (venv not found, timeout, etc.) are also checked as failure.
    throw new MergeFailure(refusal('DECISIONS_UNCHECKED', 'later',
      `couldn't check whether this PR's decisions are built (${fullError.slice(0, 100)})`,
      'Approve again in a moment. The merge server will retry the check.'))
  }
  // Process the successful result.
  if (!result) {
    // Empty stdout: fail closed.
    throw new MergeFailure(refusal('DECISIONS_UNCHECKED', 'later',
      `couldn't check whether this PR's decisions are built (empty response)`,
      'Approve again in a moment. The merge server will retry the check.'))
  }
  if (result.startsWith('filed') || result.startsWith('already filed')) {
    // A follow-up was filed; the owner must address it before the merge can proceed.
    throw new MergeFailure(refusal('DECISIONS_UNBUILT', 'reengage',
      `owner's decisions on this PR aren't built yet`,
      'The merge queue filed a follow-up ticket "Act on owner decisions" (#...). MARVIN will work through it and post a reply here before the merge can proceed.'))
  }
  if (result.includes('skipped') || result.includes('could not')) {
    // Something went wrong reading GitHub; we can't tell if decisions are built.
    throw new MergeFailure(refusal('DECISIONS_UNCHECKED', 'later',
      `couldn't check whether this PR's decisions are built (${result.slice(0, 100)})`,
      'Approve again in a moment. The merge server will retry the check.'))
  }
  if (result.includes('nothing to request')) {
    // No decisions on this PR, so nothing to build.
    return
  }
}
