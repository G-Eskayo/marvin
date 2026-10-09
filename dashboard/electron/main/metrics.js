import { readFileSync, existsSync, readdirSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

// Mirrors metrics_registry.py's storage format exactly (G-Eskayo/marvin#2):
// per-machine JSON files (one per subsystem per machine), each a list of
// {timestamp, metrics} snapshots, plus legacy flat files for historical
// data. This module is a read-only viewer -- it never writes back to these
// files (that's the Python registry's job), matching the "no cloud
// round-trip, read local data directly" requirement.
export const DEFAULT_METRICS_DIR = join(homedir(), '.agents', 'bench', 'metrics')

function parseFilename(stem) {
  // Parse <subsystem>.<machine> and <subsystem> (legacy) formats.
  // Convention: subsystem names never contain dots; machine labels are
  // alphanumeric + hyphen (mac-mini, macbook-pro, etc.).
  if (!stem.includes('.')) {
    return [stem, null]
  }
  const lastDot = stem.lastIndexOf('.')
  const subsystem = stem.substring(0, lastDot)
  const candidate = stem.substring(lastDot + 1)
  // Check if it looks like a machine name (all alphanumeric + hyphen)
  const isMachine = /^[a-zA-Z0-9-]+$/.test(candidate)
  if (isMachine) {
    return [subsystem, candidate]
  }
  return [stem, null]
}

export function listSubsystems(metricsDir = DEFAULT_METRICS_DIR) {
  if (!existsSync(metricsDir)) return []
  const subsystems = new Set()
  for (const file of readdirSync(metricsDir)) {
    if (file.endsWith('.json')) {
      const [subsystem] = parseFilename(file.slice(0, -'.json'.length))
      subsystems.add(subsystem)
    }
  }
  return Array.from(subsystems).sort()
}

function loadJsonFile(path) {
  if (!existsSync(path)) return null
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf-8'))
    return Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function readHistory(subsystem, metricsDir = DEFAULT_METRICS_DIR) {
  const allSnapshots = []

  // Load per-machine files
  if (existsSync(metricsDir)) {
    for (const file of readdirSync(metricsDir)) {
      if (file.endsWith('.json')) {
        const [sub, machine] = parseFilename(file.slice(0, -'.json'.length))
        if (sub === subsystem && machine) {
          const path = join(metricsDir, file)
          const snapshots = loadJsonFile(path)
          if (snapshots) allSnapshots.push(...snapshots)
        }
      }
    }
  }

  // Load legacy flat file if it exists
  const legacyPath = join(metricsDir, `${subsystem}.json`)
  const legacySnapshots = loadJsonFile(legacyPath)
  if (legacySnapshots) {
    allSnapshots.push(...legacySnapshots)
  }

  // Sort by timestamp ascending (oldest first) so latest comes last
  allSnapshots.sort((a, b) => {
    const aTime = new Date(a.timestamp || '').getTime()
    const bTime = new Date(b.timestamp || '').getTime()
    return aTime - bTime
  })

  return allSnapshots
}

export function latest(subsystem, metricsDir = DEFAULT_METRICS_DIR) {
  const history = readHistory(subsystem, metricsDir)
  if (history.length === 0) return null
  return history[history.length - 1]  // Ascending sort, so last is latest
}

export function buildIndex(metricsDir = DEFAULT_METRICS_DIR) {
  const index = {}
  for (const subsystem of listSubsystems(metricsDir)) {
    const snapshot = latest(subsystem, metricsDir)
    if (snapshot) index[subsystem] = snapshot
  }
  return index
}
