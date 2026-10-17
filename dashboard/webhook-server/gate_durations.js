import { appendFileSync, mkdirSync } from 'fs'
import path from 'path'
import os from 'os'

export const DEFAULT_TEST_TIMEOUT_MS = 1200_000
export const GATE_TIMEOUT_CEILING_MS = 40 * 60_000
export const GATE_OVERHEAD_MS = 5 * 60_000

const defaultPath = () => path.join(os.homedir(), '.claude', 'logs', 'gate-run-durations.jsonl')

function defaultAppend(file, line) {
  mkdirSync(path.dirname(file), { recursive: true })
  appendFileSync(file, line)
}

// Record a single duration entry for a gate run
export function recordDuration(
  { label, durationMs, countConcurrent },
  append = defaultAppend,
  now = () => new Date(),
  file = defaultPath()
) {
  try {
    const record = {
      t: now().toISOString(),
      label,
      durationMs: Math.round(durationMs),
      ...(countConcurrent !== undefined ? { countConcurrent } : {})
    }
    append(file, JSON.stringify(record) + '\n')
    return record
  } catch {
    return null
  }
}

// Read the log file and extract all durations for a given label
export function recentPassingDurations(
  label,
  file = defaultPath(),
  read = (f) => {
    try {
      const fs = require('fs')
      return fs.readFileSync(f, 'utf-8')
    } catch {
      return ''
    }
  }
) {
  const content = read(file)
  const durations = []
  for (const line of content.split('\n')) {
    if (!line.trim()) continue
    try {
      const record = JSON.parse(line)
      if (record.label === label && typeof record.durationMs === 'number') {
        durations.push(record.durationMs)
      }
    } catch {
      // ignore malformed lines
    }
  }
  return durations
}

// Calculate median of an array of numbers
export function median(values) {
  if (!values || values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid]
}

// Compute a sized timeout based on recent history and concurrency
export function sizedTimeoutMs(
  label,
  { historySamples = 10, concurrencyFactor = 1.5, minMs = 600_000, maxMs = GATE_TIMEOUT_CEILING_MS },
  file = defaultPath(),
  read = (f) => {
    try {
      const fs = require('fs')
      return fs.readFileSync(f, 'utf-8')
    } catch {
      return ''
    }
  }
) {
  const durations = recentPassingDurations(label, file, read)
  if (durations.length === 0) return minMs

  const recent = durations.slice(-historySamples)
  const med = median(recent)
  if (med === null) return minMs

  const sized = Math.round(med * concurrencyFactor)
  return Math.max(minMs, Math.min(sized, maxMs))
}

// Compute per-step timeouts for a list of steps (e.g. ['pytest', 'vitest'])
export function sizedStepTimeouts(
  steps,
  options = {},
  file = defaultPath(),
  read = (f) => {
    try {
      const fs = require('fs')
      return fs.readFileSync(f, 'utf-8')
    } catch {
      return ''
    }
  }
) {
  const result = {}
  for (const step of steps) {
    result[step] = sizedTimeoutMs(step, options, file, read)
  }
  return result
}

// Compute the gate timeout from recent history of a set of gate labels
export function computeGateTimeoutMs(
  gateLabels = ['pytest', 'vitest'],
  options = {},
  file = defaultPath(),
  read = (f) => {
    try {
      const fs = require('fs')
      return fs.readFileSync(f, 'utf-8')
    } catch {
      return ''
    }
  }
) {
  let maxGateMs = DEFAULT_TEST_TIMEOUT_MS
  for (const label of gateLabels) {
    const timeout = sizedTimeoutMs(label, options, file, read)
    maxGateMs = Math.max(maxGateMs, timeout)
  }
  // Add overhead for the rebase + setup steps
  const total = maxGateMs + GATE_OVERHEAD_MS
  return Math.min(total, GATE_TIMEOUT_CEILING_MS)
}

// Count concurrent pytest processes currently running
export function countConcurrentPytest(
  now = () => new Date(),
  file = defaultPath(),
  read = (f) => {
    try {
      const fs = require('fs')
      return fs.readFileSync(f, 'utf-8')
    } catch {
      return ''
    }
  }
) {
  const content = read(file)
  const currentTime = now()
  const recentWindowMs = 60_000 // last 60 seconds
  let count = 0

  for (const line of content.split('\n')) {
    if (!line.trim()) continue
    try {
      const record = JSON.parse(line)
      if (record.label === 'pytest' && record.countConcurrent !== undefined) {
        const recordTime = new Date(record.t)
        if (currentTime - recordTime < recentWindowMs) {
          count = Math.max(count, record.countConcurrent)
        }
      }
    } catch {
      // ignore malformed lines
    }
  }

  return count
}
