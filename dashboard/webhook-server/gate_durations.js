import { readFileSync, writeFileSync, appendFileSync, mkdirSync } from 'fs'
import path from 'path'
import { homedir } from 'os'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export const DEFAULT_TEST_TIMEOUT_MS = 1200_000
export const GATE_TIMEOUT_CEILING_MS = 40 * 60_000

const DEFAULT_LOG_PATH = path.join(homedir(), '.claude', 'logs', 'gate-run-durations.jsonl')

function ensureLogPath(logPath = DEFAULT_LOG_PATH) {
  const dir = path.dirname(logPath)
  mkdirSync(dir, { recursive: true })
  return logPath
}

function readJsonlLines(logPath) {
  try {
    const content = readFileSync(logPath, 'utf-8')
    return content.split('\n').filter(Boolean).map(line => {
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

export function recordDuration(testType, durationMs, options = {}) {
  const { logPath = DEFAULT_LOG_PATH } = options
  const fullPath = ensureLogPath(logPath)
  const entry = {
    timestamp: new Date().toISOString(),
    testType,
    durationMs,
    success: options.success !== false
  }
  appendFileSync(fullPath, JSON.stringify(entry) + '\n', 'utf-8')
}

export function recentPassingDurations(testType, options = {}) {
  const { logPath = DEFAULT_LOG_PATH, limit = 50 } = options
  const lines = readJsonlLines(logPath)
  return lines
    .filter(entry => entry.testType === testType && entry.success !== false)
    .slice(-limit)
    .map(entry => entry.durationMs)
}

export function median(durations) {
  if (!durations || durations.length === 0) return DEFAULT_TEST_TIMEOUT_MS
  const sorted = [...durations].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 0) {
    return Math.round((sorted[mid - 1] + sorted[mid]) / 2)
  }
  return sorted[mid]
}

export function sizedTimeoutMs(testType, options = {}) {
  const { capMs = DEFAULT_TEST_TIMEOUT_MS, logPath = DEFAULT_LOG_PATH, multiplier = 1.5 } = options
  const durations = recentPassingDurations(testType, { logPath })
  if (durations.length === 0) {
    return Math.min(capMs, DEFAULT_TEST_TIMEOUT_MS)
  }
  const med = median(durations)
  const sized = Math.ceil(med * multiplier)
  return Math.min(capMs, sized)
}

export async function countConcurrentPytest(exec) {
  try {
    const { stdout } = await exec('python3', ['-m', 'pytest', '--co', '-q'])
    const lines = String(stdout).split('\n').filter(Boolean)
    return Math.max(1, Math.ceil(lines.length / 10))
  } catch {
    return 1
  }
}

export function computeGateTimeoutMs(options = {}) {
  const {
    logPath = DEFAULT_LOG_PATH,
    pytestCapMs = DEFAULT_TEST_TIMEOUT_MS,
    vitestCapMs = DEFAULT_TEST_TIMEOUT_MS,
    verifyCapMs = DEFAULT_TEST_TIMEOUT_MS,
    concurrentCount = 1
  } = options

  const pytestSized = sizedTimeoutMs('pytest', { capMs: pytestCapMs, logPath })
  const vitestSized = sizedTimeoutMs('vitest', { capMs: vitestCapMs, logPath })

  const estimatedMs = Math.ceil((pytestSized + vitestSized) * 1.2)
  return Math.min(GATE_TIMEOUT_CEILING_MS, estimatedMs)
}
