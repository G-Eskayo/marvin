import { appendFileSync, mkdirSync } from 'fs'
import { dirname } from 'path'
import { homedir } from 'os'
import path from 'path'

// Log a single stage event to the voice latency log
export async function logStage(turnId, stage, tsMs, opts = {}) {
  const logPath = opts.path || path.join(homedir(), '.claude', 'logs', 'voice-latency.jsonl')

  // Ensure directory exists
  try {
    mkdirSync(dirname(logPath), { recursive: true })
  } catch {}

  const line = JSON.stringify({
    turnId,
    stage,
    tsMs,
    timestamp: new Date().toISOString()
  })

  appendFileSync(logPath, line + '\n', 'utf-8')
}
