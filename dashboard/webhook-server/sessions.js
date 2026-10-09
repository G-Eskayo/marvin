import { readFileSync, existsSync } from 'fs'
import path from 'path'
import os from 'os'

// Live sessions from session_work.py's state file, for cross-machine visibility (#331).
export const SESSIONS_STATE_PATH = path.join(os.homedir(), '.claude', 'logs', 'sessions-active.json')

export function readLiveSessions(file = SESSIONS_STATE_PATH) {
  if (!existsSync(file)) return {}
  try {
    const data = JSON.parse(readFileSync(file, 'utf-8'))
    const sessions = data.sessions || {}
    if (typeof sessions !== 'object') return {}
    return sessions
  } catch {
    return {}
  }
}
