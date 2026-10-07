import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs'
import path from 'path'
import os from 'os'

// The latest post-merge rebase result per open PR (#225), keyed by PR url: {url, pr, state, files, at, after}.
// state: clean | conflict | tests_failed | error. Lives on the machine running the webhook; the dashboard reads it
// through GET /rebase-status, because the MacBook's dashboard cannot see the mac-mini's files.
export const REBASE_STATUS_PATH = path.join(os.homedir(), '.claude', 'logs', 'pr-rebase-status.json')
const KEEP_MS = 7 * 24 * 3600 * 1000

export function readRebaseStatus(file = REBASE_STATUS_PATH) {
  if (!existsSync(file)) return {}
  try {
    return JSON.parse(readFileSync(file, 'utf-8'))
  } catch {
    return {}
  }
}

export function writeRebaseStatus(entries, file = REBASE_STATUS_PATH, now = () => new Date()) {
  const horizon = now().getTime() - KEEP_MS
  const all = { ...readRebaseStatus(file) }
  for (const e of entries) all[e.url] = e
  const kept = Object.fromEntries(Object.entries(all).filter(([, e]) => Date.parse(e.at) >= horizon))
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, JSON.stringify(kept, null, 2))
}
