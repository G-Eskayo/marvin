import path from 'path'
import { fileURLToPath } from 'url'
import { MergeFailure, refusal } from './failure.js'
import { summarizeDecisions, vagueness } from './decisions.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OWNER_DECISIONS = path.join(__dirname, '..', '..', 'lib', 'owner_decisions.py')
const VENV_PYTHON = path.join(__dirname, '..', '..', 'venv', 'bin', 'python')

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

// The merge gate refuses a PR whose owner has answered Decisions but that work isn't built yet (marvin#1261). Like the
// Decisions check, fails closed: the PR can be approved again once answers are built. Only for open PRs (the check
// runs before the merge); a merged PR with unaddressed answers keeps its follow-up ticket open (lib/owner_decisions.py).
export async function assertAnswersBuilt(prUrl, exec) {
  let repo, number
  try {
    const url = new URL(prUrl)
    const parts = url.pathname.split('/')
    repo = `${parts[1]}/${parts[2]}`
    number = Number(parts[4])
    if (!repo || !Number.isFinite(number)) throw new Error('invalid PR URL')
  } catch (error) {
    throw new MergeFailure(refusal('DECISIONS_UNCHECKED', 'request',
      `couldn't parse this PR's URL (${error?.message || error})`,
      'Report this to MARVIN. The PR was not sent back.'))
  }
  let status
  try {
    const { stdout } = await exec(VENV_PYTHON, [
      OWNER_DECISIONS, 'status', '--repo', repo, '--pr', String(number)
    ], { timeout: 60_000 })
    if (!stdout || typeof stdout !== 'string') {
      throw new Error(`no status returned for ${repo}#${number}`)
    }
    status = JSON.parse(String(stdout))
  } catch (error) {
    const reason = String(error?.stderr || error?.message || error).split('\n')[0].slice(0, 200)
    throw new MergeFailure(refusal('DECISIONS_UNCHECKED', 'request',
      `couldn't check if this PR's answers are built (${reason})`,
      'Approve again in a moment. A PR whose owner has answered needs MARVIN to act on those answers first.'))
  }
  if (status && !status.addressed_by && !status.built_since) {
    throw new MergeFailure(refusal('DECISIONS_UNBUILT', 'request',
      `this PR's owner has answered, but those answers aren't built yet`,
      `MARVIN will act on them. Approve again once the work is done. The ticket is #${repo.split('/')[1]}#(search "Act on owner decisions").`))
  }
}
