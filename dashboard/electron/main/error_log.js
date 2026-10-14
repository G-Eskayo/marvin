import { appendFileSync, mkdirSync, statSync, readFileSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

// The dashboard's side of the one error log per Mac (marvin#422; lib/error_log.py owns the format and reads it).
// Lines: {t, machine, source, message, raw}. machine is left null so the reader names it the way Health does.
// Bounded: past maxBytes, only the newest keepLines lines are kept. Never throws.
export const ERROR_LOG = path.join(os.homedir(), '.claude', 'logs', 'errors.jsonl')
const MAX_MESSAGE = 500
const MAX_RAW = 4000

const text = (v) => (v instanceof Error ? `${v.name}: ${v.message}${v.stderr ? `\n${v.stderr}` : ''}` : v == null ? '' : String(v))

export function appendError({ source, message, raw = '' }, { file = ERROR_LOG, now = () => new Date(), maxBytes = 2 * 1024 * 1024, keepLines = 2000 } = {}) {
  try {
    mkdirSync(path.dirname(file), { recursive: true })
    const entry = { t: now().toISOString(), machine: null, source: String(source).slice(0, 100), message: text(message).slice(0, MAX_MESSAGE), raw: text(raw).slice(0, MAX_RAW) }
    appendFileSync(file, JSON.stringify(entry) + '\n')
    let size = 0
    try { size = statSync(file).size } catch { size = 0 }
    if (size > maxBytes) {
      const lines = readFileSync(file, 'utf-8').split('\n').filter(Boolean)
      writeFileSync(file, lines.slice(-keepLines).join('\n') + '\n')
    }
  } catch { /* recording must never break the call that failed */ }
}
