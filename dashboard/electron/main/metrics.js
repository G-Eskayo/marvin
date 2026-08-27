import { readFileSync, existsSync, readdirSync } from 'fs'
import { join } from 'path'
import { homedir } from 'os'

// Mirrors metrics_registry.py's storage format exactly (G-Eskayo/marvin#2):
// one JSON file per subsystem, a list of {timestamp, metrics} snapshots,
// where metrics maps name -> {value, higher_is_better}. This module is a
// read-only viewer -- it never writes back to these files (that's the
// Python registry's job), matching the "no cloud round-trip, read local
// data directly" requirement.
export const DEFAULT_METRICS_DIR = join(homedir(), '.agents', 'bench', 'metrics')

export function listSubsystems(metricsDir = DEFAULT_METRICS_DIR) {
  if (!existsSync(metricsDir)) return []
  return readdirSync(metricsDir)
    .filter((f) => f.endsWith('.json'))
    .map((f) => f.slice(0, -'.json'.length))
    .sort()
}

export function readHistory(subsystem, metricsDir = DEFAULT_METRICS_DIR) {
  const path = join(metricsDir, `${subsystem}.json`)
  if (!existsSync(path)) return []
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf-8'))
    return Array.isArray(parsed) ? parsed : []
  } catch {
    // A partially-written or corrupt file shouldn't crash the dashboard --
    // surface it as "no data" for this subsystem rather than throwing.
    return []
  }
}

export function latest(subsystem, metricsDir = DEFAULT_METRICS_DIR) {
  const history = readHistory(subsystem, metricsDir)
  if (history.length === 0) return null
  return history[history.length - 1]
}

export function buildIndex(metricsDir = DEFAULT_METRICS_DIR) {
  const index = {}
  for (const subsystem of listSubsystems(metricsDir)) {
    const snapshot = latest(subsystem, metricsDir)
    if (snapshot) index[subsystem] = snapshot
  }
  return index
}
