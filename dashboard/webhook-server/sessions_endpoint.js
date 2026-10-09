import { readFileSync, existsSync } from 'fs'
import path from 'path'
import os from 'os'

// Live sessions keyed by session id, similar to rebase_status.js but for active sessions.
export const SESSIONS_PATH = path.join(os.homedir(), '.claude', 'logs', 'sessions-active.json')

export function readSessionsSnapshot(file = SESSIONS_PATH) {
  if (!existsSync(file)) return {}
  try {
    return JSON.parse(readFileSync(file, 'utf-8'))
  } catch {
    return {}
  }
}
