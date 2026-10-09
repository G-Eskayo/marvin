import { readFileSync, existsSync, readdirSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

// Mirrors metrics_registry.py's per-machine storage format (G-Eskayo/marvin#2):
// per-machine JSON files ({subsystem}.{machine}.json), legacy bare files
// ({subsystem}.json), each a list of {timestamp, metrics} snapshots where metrics
// maps name -> {value, higher_is_better}. This module is read-only -- it never
// writes (that's the Python registry's job), matching the "no cloud round-trip,
// read local data directly" requirement.
export const DEFAULT_METRICS_DIR = join(homedir(), '.agents', 'bench', 'metrics')

export function listSubsystems(metricsDir = DEFAULT_METRICS_DIR) {
  if (!existsSync(metricsDir)) return []
  const subsystems = new Set()
  readdirSync(metricsDir)
    .filter((f) => f.endsWith('.json'))
    .forEach((f) => {
      const name = f.slice(0, -'.json'.length)
      const lastDot = name.lastIndexOf('.')
      // If there's a dot, the part before it is the subsystem; otherwise it's the whole name
      if (lastDot > 0) {
        subsystems.add(name.slice(0, lastDot))
      } else {
        subsystems.add(name)
      }
    })
  return Array.from(subsystems).sort()
}

function readHistoryForMachine(subsystem, machine, metricsDir) {
  let path
  if (machine === 'legacy') {
    path = join(metricsDir, `${subsystem}.json`)
  } else {
    path = join(metricsDir, `${subsystem}.${machine}.json`)
  }
  if (!existsSync(path)) return []
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf-8'))
    if (!Array.isArray(parsed)) return []
    return parsed.map(entry => ({ ...entry, machine }))
  } catch {
    return []
  }
}

export function readHistory(subsystem, metricsDir = DEFAULT_METRICS_DIR) {
  // Merge every machine's history for this subsystem into one timeline, each
  // entry tagged with a machine field, sorted by timestamp.
  if (!existsSync(metricsDir)) return []

  const allEntries = []
  const machines = new Set()

  // Find all machines' files for this subsystem
  readdirSync(metricsDir)
    .filter((f) => f.endsWith('.json'))
    .forEach((f) => {
      const name = f.slice(0, -'.json'.length)
      const lastDot = name.lastIndexOf('.')
      if (lastDot > 0) {
        const sub = name.slice(0, lastDot)
        const machine = name.slice(lastDot + 1)
        if (sub === subsystem) machines.add(machine)
      } else if (name === subsystem) {
        machines.add('legacy')
      }
    })

  // Read and merge all machines' histories
  for (const machine of machines) {
    allEntries.push(...readHistoryForMachine(subsystem, machine, metricsDir))
  }

  // Sort by timestamp (chronologically)
  return allEntries.sort((a, b) => {
    const aTs = new Date(a.timestamp).getTime()
    const bTs = new Date(b.timestamp).getTime()
    return aTs - bTs
  })
}

export function latest(subsystem, metricsDir = DEFAULT_METRICS_DIR) {
  const history = readHistory(subsystem, metricsDir)
  if (history.length === 0) return null
  return history[history.length - 1]
}

export function buildIndex(metricsDir = DEFAULT_METRICS_DIR) {
  // Build index showing the single most-recent snapshot across all machines per subsystem.
  // Structure: {subsystem: {timestamp, metrics, machine}, ...}
  // Delegates to latest() which already merges all machines and returns the newest entry.
  const index = {}
  for (const subsystem of listSubsystems(metricsDir)) {
    const snap = latest(subsystem, metricsDir)
    if (snap) {
      index[subsystem] = snap
    }
  }
  return index
}
