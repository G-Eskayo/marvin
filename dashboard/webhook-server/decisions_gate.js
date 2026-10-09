import { MergeFailure, refusal } from './failure.js'
import { summarizeDecisions, vagueness } from './decisions.js'

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
