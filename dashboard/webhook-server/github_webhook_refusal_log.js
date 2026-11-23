import { appendFileSync, mkdirSync, statSync, renameSync } from 'fs'
import path from 'path'
import os from 'os'

// marvin#566: webhook refusal logging with rotation (unbounded growth prevention, ADR 0065).
// When refusal log exceeds REFUSAL_LOG_MAX_SIZE, rotate: shift existing numbered files and start fresh.

const REFUSAL_LOG_MAX_SIZE = 10 * 1024 * 1024 // 10 MB
const REFUSAL_LOG_MAX_ROTATIONS = 3

export function createRefusalLogger(home = process.env.HOME) {
  return (line) => {
    const file = path.join(home, '.claude', 'logs', 'github-webhook-refusals.jsonl')
    // Fail-soft on directory creation (home may not exist or be writable).
    try {
      mkdirSync(path.dirname(file), { recursive: true })
    } catch {
      return // Can't write to log, give up silently.
    }

    // Check file size and rotate if needed (fail-soft on stat/rename errors).
    try {
      const stat = statSync(file)
      if (stat.size + line.length > REFUSAL_LOG_MAX_SIZE) {
        // Rotate: shift existing rotations and start fresh.
        for (let i = REFUSAL_LOG_MAX_ROTATIONS - 1; i > 0; i--) {
          const old = `${file}.${i - 1}`
          const next = `${file}.${i}`
          try { renameSync(old, next) } catch {}
        }
        try { renameSync(file, `${file}.0`) } catch {}
      }
    } catch {}

    // Fail-soft on append (log file may have permission issues).
    try {
      appendFileSync(file, line)
    } catch {}
  }
}

export function getRefusalLogFile(home = process.env.HOME) {
  return path.join(home, '.claude', 'logs', 'github-webhook-refusals.jsonl')
}
