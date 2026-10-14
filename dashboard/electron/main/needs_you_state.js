import { readFileSync, writeFileSync, mkdirSync } from 'fs'
import { dirname } from 'path'

// Read "needs you" state from disk: always returns { rows, at, sort } with defaults,
// matching the structure that prefs.js uses for per-field type checking
export function readNeedsYouState(path) {
  try {
    const text = readFileSync(path, 'utf8')
    const data = JSON.parse(text)
    // Validate structure per field, matching prefs.js pattern
    const out = { rows: [], at: 0, sort: null }
    if (data && typeof data === 'object') {
      if (Array.isArray(data.rows)) out.rows = data.rows
      if (typeof data.at === 'number') out.at = data.at
      if (data.sort === null || typeof data.sort === 'string') out.sort = data.sort
    }
    return out
  } catch {
    return { rows: [], at: 0, sort: null }
  }
}

// Write "needs you" state to disk: merge-write (read-current, shallow-merge, write).
// Never throws, swallows mkdirSync and writeFileSync errors (best-effort).
export function writeNeedsYouState(path, partial) {
  try {
    // Read current state
    const current = readNeedsYouState(path)
    // Shallow merge the partial into current
    const merged = { ...current, ...partial }
    // Write back
    try {
      mkdirSync(dirname(path), { recursive: true })
    } catch {
      // Directory creation failed, but keep going
    }
    try {
      writeFileSync(path, JSON.stringify(merged, null, 2), 'utf8')
    } catch {
      // Write failed, but never throw
    }
  } catch {
    // Never throw
  }
}
