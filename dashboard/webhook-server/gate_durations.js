import { appendFileSync, mkdirSync, readFileSync } from 'fs'
import path from 'path'
import os from 'os'

const defaultPath = () => path.join(os.homedir(), '.claude', 'logs', 'gate-run-durations.jsonl')

function defaultAppend(file, line) {
  mkdirSync(path.dirname(file), { recursive: true })
  appendFileSync(file, line)
}

function defaultNow() {
  return Date.now()
}

function defaultExec() {
  // Return the number of concurrent pytest processes running
  // For now, return 0 as default (will be mocked in tests)
  return 0
}

// Default values for timeout configuration
export const DEFAULT_TEST_TIMEOUT_MS = 1200_000
export const GATE_TIMEOUT_CEILING_MS = 40 * 60_000
export const GATE_OVERHEAD_MS = 5 * 60_000

// Record a test step's duration. step = 'pytest', 'vitest', or 'verify:repo_name'
export function recordDuration(
  { step, ms, passed },
  append = defaultAppend,
  now = defaultNow,
  file = defaultPath()
) {
  try {
    const record = {
      t: new Date(now()).toISOString(),
      kind: 'duration',
      step,
      ms: Math.round(ms),
      passed: !!passed
    }
    append(file, JSON.stringify(record) + '\n')
    return record
  } catch {
    return null
  }
}

// Get recent passing durations for a step from the log file
export function recentPassingDurations(
  step,
  file = defaultPath(),
  limit = 10,
  readFile = (f) => {
    try {
      return readFileSync(f, 'utf-8').split('\n').filter(Boolean)
    } catch {
      return []
    }
  }
) {
  try {
    const lines = readFile(file)
    return lines
      .map((line) => {
        try {
          return JSON.parse(line)
        } catch {
          return null
        }
      })
      .filter((r) => r && r.kind === 'duration' && r.step === step && r.passed)
      .slice(-limit)
      .map((r) => r.ms)
  } catch {
    return []
  }
}

// Compute the median of a list of numbers
export function median(nums) {
  if (!nums.length) return 0
  const sorted = [...nums].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid]
}

// Count concurrent pytest processes
export function countConcurrentPytest() {
  // This would typically use ps/pgrep to count processes
  // For now, always return 0 (single process) since the default is not concurrent
  // Tests will mock this
  return 0
}

// Get sized timeouts for a list of test steps based on their history
// Returns { step: timeoutMs } for each step
export function sizedStepTimeouts(
  steps,
  fileReader = (file) => {
    try {
      return readFileSync(file, 'utf-8').split('\n').filter(Boolean)
    } catch {
      return []
    }
  },
  file = defaultPath()
) {
  const result = {}
  const lines = fileReader(file)

  for (const step of steps) {
    const durations = lines
      .map((line) => {
        try {
          return JSON.parse(line)
        } catch {
          return null
        }
      })
      .filter((r) => r && r.kind === 'duration' && r.step === step && r.passed)
      .map((r) => r.ms)

    if (durations.length === 0) {
      // No history: use default timeout
      result[step] = DEFAULT_TEST_TIMEOUT_MS
    } else {
      const med = median(durations)
      // Timeout is median + generous overhead (50% buffer for variability)
      result[step] = Math.max(DEFAULT_TEST_TIMEOUT_MS, Math.round(med * 1.5))
    }
  }

  return result
}

// Compute the overall gate timeout based on expected step durations
// steps = ['pytest', 'vitest'] or ['verify:repo_name']
export function computeGateTimeoutMs(
  steps,
  fileReader = (file) => {
    try {
      return readFileSync(file, 'utf-8').split('\n').filter(Boolean)
    } catch {
      return []
    }
  },
  file = defaultPath()
) {
  const timeouts = sizedStepTimeouts(steps, fileReader, file)
  const totalMs = Object.values(timeouts).reduce((sum, ms) => sum + ms, 0)
  // Add overhead for git operations (fetch, rebase, push)
  const withOverhead = totalMs + GATE_OVERHEAD_MS
  // Never exceed the ceiling
  return Math.min(withOverhead, GATE_TIMEOUT_CEILING_MS)
}
