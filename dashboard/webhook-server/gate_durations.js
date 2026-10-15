import { appendFileSync, readFileSync, mkdirSync } from 'fs'
import path from 'path'
import os from 'os'

// Records how long a gate (or test run) took and whether it passed, so we can:
// 1. Determine a "usual" duration for that gate (median of recent runs)
// 2. Derive a timeout that's generous to normal cases but catches real hangs
// 3. Adjust the outer GATE_TIMEOUT_MS based on what we've observed
//
// Fail-soft by design: recording must never break or mask the failure being recorded.
// Modeled on failure_log.js but for duration data instead of failures.

export const DEFAULT_TEST_TIMEOUT_MS = 1200_000

const defaultPath = () => path.join(os.homedir(), '.claude', 'logs', 'gate-run-durations.jsonl')

function defaultAppend(file, line) {
  mkdirSync(path.dirname(file), { recursive: true })
  appendFileSync(file, line)
}

function defaultRead(file) {
  try {
    const text = readFileSync(file, 'utf-8')
    return text.split('\n').filter(Boolean).map((line) => {
      try {
        return JSON.parse(line)
      } catch {
        return null
      }
    }).filter(Boolean)
  } catch {
    return []
  }
}

// Record a single gate/test run: duration, pass/fail status, and a key (e.g. 'pytest', 'vitest', 'verify:G-Eskayo/clarity-captions').
// Fail-soft: catch any errors and return null instead of throwing.
export function recordDuration({ key, durationMs, passed }, append = defaultAppend, now = () => new Date(), file = defaultPath()) {
  try {
    const record = {
      t: now().toISOString(),
      key,
      durationMs: Math.round(durationMs),
      passed: Boolean(passed)
    }
    append(file, JSON.stringify(record) + '\n')
    return record
  } catch {
    return null
  }
}

// Get the median duration of recent passing runs for a given key.
// Returns null if no data, or the calculated median in ms.
export function recentPassingDurations(key, { file = defaultPath(), read = defaultRead, limit = 10 } = {}) {
  try {
    const records = read(file)
    const passing = records
      .filter((r) => r.key === key && r.passed)
      .slice(-limit)
      .map((r) => r.durationMs)

    if (passing.length === 0) return null
    return median(passing)
  } catch {
    return null
  }
}

// Calculate the median of an array of numbers.
export function median(values) {
  if (!Array.isArray(values) || values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid]
}

// Derive a timeout for a gate based on historical performance:
// - floorMs: minimum timeout (absolute floor, e.g. 20 min for any gate)
// - multiplier: how many times the median we're willing to wait (default 3x)
// - capMs: maximum timeout (outer limit, e.g. GATE_TIMEOUT_MS)
//
// Example: if the median duration is 10 min, multiplier is 3, and cap is 40 min,
// the timeout will be min(40, max(20, 10*3)) = 30 min.
//
// Returns the computed timeout in ms, or floorMs if no historical data is available.
export function sizedTimeoutMs(key, { floorMs = DEFAULT_TEST_TIMEOUT_MS, multiplier = 3, capMs = DEFAULT_TEST_TIMEOUT_MS, file = defaultPath(), read = defaultRead } = {}) {
  const median = recentPassingDurations(key, { file, read })
  if (median === null) {
    return floorMs
  }
  const derived = Math.round(median * multiplier)
  return Math.min(capMs, Math.max(floorMs, derived))
}

// Count concurrent pytest processes running on this machine.
// Returns the count, or null if pgrep fails or is unavailable.
// Exit 1 from pgrep means "no match found", which we treat as 0.
export function countConcurrentPytest(exec) {
  try {
    // pgrep returns a count when run with -c (count mode), or a list of PIDs otherwise.
    // We use -c and -f for full command matching.
    const result = exec('pgrep', ['-c', '-f', 'pytest'], { stdio: 'pipe', shell: false })
    const count = parseInt(String(result.stdout || result).trim(), 10)
    return isNaN(count) ? null : count
  } catch (e) {
    // pgrep exits with 1 when no matches are found, which is not an error.
    // execSync throws with status property, execFile has code property.
    if (e?.status === 1 || e?.code === 1) return 0
    // ENOENT means pgrep is not available on this machine (or PATH is wrong).
    // Other errors are unexpected; return null to indicate "unavailable".
    return null
  }
}
