import { appendFileSync, mkdirSync } from 'fs'
import path from 'path'
import os from 'os'

// Writes approve/merge failures into the SAME append-only log the ticket pipeline's
// circuit breaker reads (lib/failure_breaker.py, ~/.claude/logs/pipeline-failures.jsonl),
// so "GH_AUTH_INVALID on three different PRs" trips the breaker and shows red on the
// Health tab exactly like any other systemic pipeline failure. The contract is the
// JSON line shape: {t: ISO time, kind: "failure", ticket: int, sig: str, reason: str}.
// Fail-soft by design: recording must never break or mask the failure being recorded.

const defaultPath = () => path.join(os.homedir(), '.claude', 'logs', 'pipeline-failures.jsonl')

function defaultAppend(file, line) {
  mkdirSync(path.dirname(file), { recursive: true })
  appendFileSync(file, line)
}

export function recordFailure({ ticket, code, message }, append = defaultAppend, now = () => new Date(), file = defaultPath()) {
  try {
    const record = {
      t: now().toISOString(),
      kind: 'failure',
      ticket: Number(ticket),
      sig: `merge:${code}`,
      reason: `${code}: ${message}`.slice(0, 300)
    }
    append(file, JSON.stringify(record) + '\n')
    return record
  } catch {
    return null
  }
}
