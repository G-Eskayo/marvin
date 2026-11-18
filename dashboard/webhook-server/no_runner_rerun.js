import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs'
import path from 'path'
import os from 'os'

// Record of no-runner reruns: one per head SHA + run ID per PR. Lives on the machine running
// the dashboard main process (Electron). Keyed by repo#number@headSha@runId.
export const NO_RUNNER_RERUN_PATH = path.join(os.homedir(), '.claude', 'logs', 'no-runner-reruns.json')
const KEEP_MS = 7 * 24 * 3600 * 1000

export function noRunnerKey(repo, number, headSha, runId) {
  return `${repo}#${number}@${headSha}@${runId}`
}

export function readNoRunnerReruns(file = NO_RUNNER_RERUN_PATH) {
  if (!existsSync(file)) return {}
  try {
    return JSON.parse(readFileSync(file, 'utf-8'))
  } catch {
    return {}
  }
}

export function recordNoRunnerRerun(key, entry, file = NO_RUNNER_RERUN_PATH, now = () => new Date()) {
  const horizon = now().getTime() - KEEP_MS
  const all = { ...readNoRunnerReruns(file) }
  all[key] = entry
  const kept = Object.fromEntries(Object.entries(all).filter(([, e]) => Date.parse(e.at) >= horizon))
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, JSON.stringify(kept, null, 2))
}
