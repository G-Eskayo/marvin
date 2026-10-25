import { appendFileSync, mkdirSync, readFileSync } from 'fs'
import path from 'path'
import os from 'os'

// History-driven sizing for merge gate timeouts: test how long each step usually takes,
// cap it to a fixed per-step ceiling, add overhead for git/rebase/push, then use that
// to size the full gate. Same principle as execWithGroupTimeout's dependency injection.

export const DEFAULT_TEST_TIMEOUT_MS = 1200_000
export const STEP_TIMEOUT_CEILING_MS = 40 * 60_000
export const GATE_TIMEOUT_CEILING_MS = 90 * 60_000
export const GATE_OVERHEAD_MS = 5 * 60_000
const MAX_LOG_LINES_READ = 5000

const defaultPath = () => path.join(os.homedir(), '.claude', 'logs', 'gate-run-durations.jsonl')

function defaultAppend(file, line) {
  mkdirSync(path.dirname(file), { recursive: true })
  appendFileSync(file, line)
}

function defaultRead(file) {
  try {
    return readFileSync(file, 'utf-8')
  } catch {
    return ''
  }
}

function defaultNow() {
  return Date.now()
}

// Record a single step's duration: {t: ISO time, key: str, durationMs: number, passed: bool}
// Fail-soft like failure_log.js: recording must never break or mask the test result.
export function recordDuration(
  key,
  durationMs,
  passed,
  append = defaultAppend,
  now = defaultNow,
  file = defaultPath()
) {
  try {
    const record = {
      t: new Date(now()).toISOString(),
      key,
      durationMs: Math.round(durationMs),
      passed
    }
    append(file, JSON.stringify(record) + '\n')
    return record
  } catch {
    return null
  }
}

// Read all durations from the log and return the most recent ones for each key.
// Takes an array of exact key strings (not a regex). Filters to passed === true.
// Returns a map: key -> [duration1, duration2, ...] sorted newest first.
export function recentPassingDurations(
  keys,
  read = defaultRead,
  file = defaultPath(),
  maxPerKey = 10
) {
  const results = {}
  const keysSet = new Set(keys)
  const content = read(file)
  const lines = content.split('\n').filter(Boolean).slice(-MAX_LOG_LINES_READ)

  for (const line of lines) {
    try {
      const rec = JSON.parse(line)
      if (rec.key && keysSet.has(rec.key) && typeof rec.durationMs === 'number' && rec.durationMs > 0 && rec.passed === true) {
        if (!results[rec.key]) results[rec.key] = []
        results[rec.key].push(rec)
      }
    } catch { /* unparseable line */ }
  }

  // Keep only the most recent maxPerKey entries per key
  for (const key in results) {
    results[key] = results[key]
      .sort((a, b) => new Date(b.t).getTime() - new Date(a.t).getTime())
      .slice(0, maxPerKey)
      .map(r => r.durationMs)
  }

  return results
}

// Compute the median of an array of numbers
export function median(nums) {
  if (!Array.isArray(nums) || nums.length === 0) return 0
  const sorted = [...nums].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid]
}

// Size a timeout for a single test step: max(DEFAULT_TEST_TIMEOUT_MS, 3×median), cap to ceiling.
// Returns milliseconds.
export function sizedTimeoutMs(
  key,
  recentDurations,
  ceilingMs = STEP_TIMEOUT_CEILING_MS
) {
  const records = recentDurations[key] || []
  if (records.length === 0) return DEFAULT_TEST_TIMEOUT_MS
  const mid = median(records)
  const sized = Math.max(DEFAULT_TEST_TIMEOUT_MS, mid * 3)
  return Math.min(Math.ceil(sized), ceilingMs)
}

// Compute the full gate timeout from a list of step keys: sum their sized timeouts,
// add overhead for git/rebase/push, cap to the overall ceiling.
export function computeGateTimeoutMs(
  stepKeys,
  recentDurations = {},
  ceilingMs = GATE_TIMEOUT_CEILING_MS,
  overheadMs = GATE_OVERHEAD_MS
) {
  let total = overheadMs
  for (const key of stepKeys) {
    total += sizedTimeoutMs(key, recentDurations)
  }
  return Math.min(total, ceilingMs)
}

// Count how many pytest processes are currently running (for enrichment markers).
// `exec` is the execFileAsync or similar. Returns a promise resolving to the count.
// Fail-soft: returns 0 on any error (can't count, but don't break the operation).
export async function countConcurrentPytest(exec) {
  try {
    const { stdout } = await exec('pgrep', ['-f', 'pytest|vitest'])
    const count = String(stdout).split('\n').filter(Boolean).length
    return count
  } catch {
    return 0
  }
}
