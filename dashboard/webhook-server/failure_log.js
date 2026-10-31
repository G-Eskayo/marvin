import { appendFileSync, mkdirSync } from 'fs'
import path from 'path'
import os from 'os'

// Writes approve/merge failures into the SAME append-only log the ticket pipeline's
// circuit breaker reads (lib/failure_breaker.py, ~/.claude/logs/pipeline-failures.jsonl),
// so "GH_AUTH_INVALID on three different PRs" trips the breaker and shows red on the
// Health tab exactly like any other systemic pipeline failure. The contract is the
// JSON line shape: {t: ISO time, kind: "failure", ticket: int, sig: str, reason: str, project?, pr_url?, stage?}.
// Fail-soft by design: recording must never break or mask the failure being recorded.

const defaultPath = () => path.join(os.homedir(), '.claude', 'logs', 'pipeline-failures.jsonl')

function defaultAppend(file, line) {
  mkdirSync(path.dirname(file), { recursive: true })
  appendFileSync(file, line)
}

export function recordFailure({ ticket, code, message, project, prUrl, stage }, append = defaultAppend, now = () => new Date(), file = defaultPath()) {
  try {
    const record = {
      t: now().toISOString(),
      kind: 'failure',
      ticket: Number(ticket),
      sig: `merge:${code}`,
      reason: `${code}: ${message}`.slice(0, 300),
      // Which project, PR and stage (#215). Without project the breaker counts every merge failure as marvin's.
      ...(project ? { project } : {}),
      ...(prUrl ? { pr_url: prUrl } : {}),
      ...(stage ? { stage } : {})
    }
    append(file, JSON.stringify(record) + '\n')
    return record
  } catch {
    return null
  }
}

// A test that failed in the merge gate, then passed when run once more (failure containment, 2026-10-30). Its own file,
// never pipeline-failures.jsonl: a flake is not a broken environment, and feeding the breaker would pause dispatch for it.
// Read later to see which tests flake most. Fail-soft like recordFailure.
const defaultFlakyPath = () => path.join(os.homedir(), '.claude', 'logs', 'flaky-tests.jsonl')

export function recordFlaky({ tests, prUrl, project }, append = defaultAppend, now = () => new Date(), file = defaultFlakyPath()) {
  try {
    const record = {
      t: now().toISOString(),
      kind: 'flaky',
      tests: (Array.isArray(tests) ? tests : []).slice(0, 15).map((n) => String(n).slice(0, 300)),
      ...(prUrl ? { pr_url: prUrl } : {}),
      ...(project ? { project } : {})
    }
    append(file, JSON.stringify(record) + '\n')
    return record
  } catch {
    return null
  }
}
