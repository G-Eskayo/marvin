import { appendFileSync, mkdirSync, readFileSync } from 'fs'
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

// Was the owner already shown every one of these flaky tests on this PR? The gate holds a flaky pass for Approve
// again (Gil 2026-10-30); the Approve that follows merges when the same test flakes again, instead of holding forever.
// Anything unreadable is false: holding is the safe side.
export function flakySeenBefore(prUrl, tests, read = () => readFileSync(defaultFlakyPath(), 'utf8')) {
  try {
    if (!prUrl || !Array.isArray(tests) || !tests.length) return false
    const seen = new Set()
    for (const line of String(read()).split('\n')) {
      let rec
      try { rec = JSON.parse(line) } catch { continue }
      if (rec && rec.kind === 'flaky' && rec.pr_url === prUrl && Array.isArray(rec.tests)) rec.tests.forEach((t) => seen.add(t))
    }
    return tests.every((t) => seen.has(String(t).slice(0, 300)))
  } catch {
    return false
  }
}
