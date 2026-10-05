import { readFileSync, readdirSync, statSync, existsSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// Reads the project catalog written by lib/project_catalog.py. Generated output
// is per machine (projects.<device>.json); shared human decisions are in
// overrides.json. The dashboard only ever reads these.
export const CATALOG_DIR = path.join(homedir(), '.claude', 'catalog')
export const MASTER_DOC_PATH = path.join(homedir(), 'Desktop', '_WHERE-THINGS-ARE.md')

const parse = (file) => {
  try {
    return JSON.parse(readFileSync(file, 'utf-8'))
  } catch {
    return null
  }
}

export function readCatalog({ dir = CATALOG_DIR, deviceId = null } = {}) {
  try {
    if (deviceId) {
      const own = path.join(dir, `projects.${deviceId}.json`)
      if (existsSync(own)) {
        const c = parse(own)
        if (c && Array.isArray(c.projects)) return c
      }
    }
    const newest = readdirSync(dir)
      .filter((n) => /^projects\..+\.json$/.test(n))
      .map((n) => ({ n, t: statSync(path.join(dir, n)).mtimeMs }))
      .sort((a, b) => b.t - a.t)[0]
    const c = newest ? parse(path.join(dir, newest.n)) : null
    return c && Array.isArray(c.projects) ? c : null
  } catch {
    return null
  }
}

export function readOverrides(dir = CATALOG_DIR) {
  const data = parse(path.join(dir, 'overrides.json'))
  if (!data || typeof data !== 'object') return {}
  return Object.fromEntries(Object.entries(data).filter(([k, v]) => !k.startsWith('_') && v && typeof v === 'object'))
}

export function readMasterDoc(file = MASTER_DOC_PATH) {
  try {
    return readFileSync(file, 'utf-8')
  } catch {
    return null
  }
}
