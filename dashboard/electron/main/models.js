import { readFileSync } from 'fs'
import { homedir, hostname } from 'os'
import path from 'path'

// Model registry: static repo file (synced via auto-sync), read once per request.
// Live queue state comes from health_checks.py's machine-state probe (merged via devices handler).
const REGISTRY_PATH = path.join(homedir(), '.agents', 'config', 'models.json')
const TTL_MS = 30000  // Repo file changes rarely; cache for 30s

let cache = null

function readRegistry() {
  try {
    const text = readFileSync(REGISTRY_PATH, 'utf-8')
    return JSON.parse(text)
  } catch (err) {
    return {}
  }
}

export async function getModelRegistry({ now = Date.now() } = {}) {
  if (cache && now - cache.at < TTL_MS) return cache.value

  const registry = readRegistry()
  const value = {
    models: Object.entries(registry).map(([name, meta]) => ({
      name,
      ...meta
    })),
    error: null
  }

  cache = { at: now, value }
  return value
}

export function clearModelCache() { cache = null }
