/**
 * merge_trend.js — thin wrapper around lib/merge_trend.py for fire-and-forget recording.
 * Called after a successful merge to record the mutation score trend for health monitoring (ADR 0063, #339).
 */

import { spawn } from 'child_process'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_PATH = path.resolve(__dirname, '..', '..')
const MERGE_TREND_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'merge_trend.py')
const VENV_PYTHON = path.resolve(__dirname, '..', '..', 'venv', 'bin', 'python')

/**
 * Extract repo from a GitHub PR URL: https://github.com/OWNER/REPO/pull/123 -> OWNER/REPO
 */
function repoFromUrl(prUrl) {
  const m = String(prUrl).match(/github\.com\/([^/]+\/[^/]+)\/pull\//)
  return m ? m[1] : null
}

/**
 * Record a merge event fire-and-forget. Called right after merge succeeded (stage('merging', 'passed')).
 * `spawnFn` is injectable for testing; defaults to spawn.
 */
export function recordMergeTrend(prUrl, repo, spawnFn = spawn) {
  const repoName = repo || repoFromUrl(prUrl)
  if (!repoName) return  // malformed URL: skip silently

  try {
    const child = spawnFn(VENV_PYTHON, [MERGE_TREND_SCRIPT, repoName, prUrl], {
      detached: true,
      stdio: 'ignore',
      cwd: REPO_PATH
    })
    // Detach the process so the parent can exit independently
    child.unref()
    // Belt-and-suspenders: attach error handler in case spawn fails (e.g., VENV_PYTHON doesn't exist)
    child.on('error', () => {})
  } catch {
    // Spawn itself might throw; fire-and-forget means we silently ignore it
  }
}
