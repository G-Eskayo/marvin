import { MergeFailure, refusal } from './failure.js'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const VENV_PYTHON = path.resolve(__dirname, '..', '..', 'venv', 'bin', 'python')
const CODE_REVIEW_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'code_review_gate.py')

// Code review gate: runs after CI and rebase checks pass, before merge. Judges the diff for
// correctness bugs and quality issues. A finding blocks merge and sends the PR back for rework;
// a clean review allows merge to proceed. Script failures (gate infrastructure problems, not PR
// problems) are escalated, not sent back.
export async function assertCodeReviewClean(
  prUrl,
  exec,
  scriptPath = CODE_REVIEW_SCRIPT
) {
  let result
  try {
    // The venv interpreter, like every other gate: launchd's PATH has no bare `python` on the mini.
    const { stdout } = await exec(VENV_PYTHON, [scriptPath, 'review', prUrl])
    result = JSON.parse(stdout)
  } catch (e) {
    // Script failed to run (ENOENT, parse error, etc.) — machine/tooling fault
    throw new MergeFailure(refusal(
      'GATE_INFRA',
      'gate',
      'the code-review check failed to run, not the PR\'s code',
      `Approve it again. The PR was not sent back for rework. Details: ${String(e && e.message || e).slice(0, 200)}`
    ))
  }

  // Handle script errors (clean is null)
  if (result.clean === null) {
    throw new MergeFailure(refusal(
      'GATE_INFRA',
      'gate',
      'the code-review check failed to run, not the PR\'s code',
      `Approve it again. The PR was not sent back for rework. Details: ${result.error}`
    ))
  }

  // Handle findings (clean is false)
  if (result.clean === false) {
    const findingsText = (result.findings || []).map((f) => `- ${f}`).join('\n')
    const message = `Code review found issues:\n\n${findingsText}`
    throw new MergeFailure(refusal(
      'CODE_REVIEW_FOUND',
      'gate',
      message,
      'Fix what the review found, then the ticket will be rebuilt.',
      'reengage'
    ))
  }

  // Clean (clean is true) — no-op, merge proceeds
}
