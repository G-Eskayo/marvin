import { MergeFailure, refusal } from './failure.js'
import { execFile } from 'child_process'
import { promisify } from 'util'
import path from 'path'
import { fileURLToPath } from 'url'

const execFileAsync = promisify(execFile)
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_PATH = path.resolve(__dirname, '..', '..')
const VENV_PYTHON = path.resolve(REPO_PATH, 'venv', 'bin', 'python')

// marvin#1261: a merged PR whose owner had answered Decisions checks whether the answers have been built since
// the merge. If not, it holds the merge approval and re-queues it, so the owner can answer again after the
// built-but-not-tested answers are tested (the merge gate).
export async function assertOwnerDecisionsBuilt(prUrl, exec = execFileAsync) {
  let repo, number
  try {
    // Extract repo and PR number from URL: https://github.com/OWNER/REPO/pull/NUMBER
    const m = String(prUrl || '').match(/github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/)
    if (!m) throw new Error('invalid URL')
    repo = m[1]
    number = parseInt(m[2], 10)
  } catch {
    throw new MergeFailure(refusal('OWNER_DECISIONS_UNCHECKED', 'request',
      `couldn't parse this PR's URL (${prUrl})`,
      'Approve again in a moment. A PR with owner decisions must have its answers built before merging.'))
  }

  let status
  try {
    const { stdout } = await exec(VENV_PYTHON, ['lib/owner_decisions.py', 'status', '--repo', repo, '--pr', String(number)], { cwd: REPO_PATH, timeout: 30000 })
    const output = String(stdout || '').trim().split('\n').pop() || '{}'
    status = JSON.parse(output)
  } catch (error) {
    throw new MergeFailure(refusal('OWNER_DECISIONS_UNCHECKED', 'request',
      `couldn't check this PR's decisions (${error?.message || error})`,
      'Approve again in a moment. A PR with owner decisions must have its answers built before merging.'))
  }

  if (!status || typeof status !== 'object') {
    throw new MergeFailure(refusal('OWNER_DECISIONS_UNCHECKED', 'request',
      `couldn't check this PR's decisions`,
      'Approve again in a moment. A PR with owner decisions must have its answers built before merging.'))
  }

  if (status.error) {
    throw new MergeFailure(refusal('OWNER_DECISIONS_UNCHECKED', 'request',
      `couldn't check this PR's decisions (${status.error})`,
      'Approve again in a moment. A PR with owner decisions must have its answers built before merging.'))
  }

  if (!status.has_decisions && status.built !== false) {
    return // No decisions, nothing to check
  }

  if (status.built === false) {
    // Answers exist but aren't built yet; hold the merge
    throw new MergeFailure(refusal('OWNER_DECISIONS_UNBUILT', 'request',
      `your answers to this PR's decisions haven't been built yet`,
      'The merge gate will test them after the merge. The PR was not changed.'))
  }
}
