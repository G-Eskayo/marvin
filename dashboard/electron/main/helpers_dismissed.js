import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { dirname } from 'path'

// Persists which chat helpers this machine's user has dismissed, so crashed/stuck
// helpers can be hidden from the home list and reappear only on a timer (#818).
// Local-only by design — "dismissed" is a per-viewer concept, not shared GitHub state.

// Returns a Map of dismissed helper keys to timestamps. Returns an empty Map if the file
// does not exist, is corrupt, or has an invalid dismissed object. Errors are silently ignored.
export function readDismissed(path) {
  if (!existsSync(path)) return new Map()
  try {
    const data = JSON.parse(readFileSync(path, 'utf-8'))
    if (typeof data.dismissed !== 'object' || data.dismissed === null) return new Map()
    return new Map(Object.entries(data.dismissed))
  } catch {
    return new Map()
  }
}

// Adds a helper key to the dismissed set. Throws if the key is invalid (non-string,
// empty, or longer than 256 characters). Creates parent directories as needed.
export function dismissHelper(path, key) {
  if (typeof key !== 'string' || key.length === 0 || key.length > 256) {
    throw new Error(`Invalid dismiss key: ${key}`)
  }
  const dismissed = readDismissed(path)
  dismissed.set(key, Date.now())
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, JSON.stringify({ dismissed: Object.fromEntries(dismissed) }))
}

export function isHelperDismissed(key, dismissed) {
  return dismissed?.has(key) ?? false
}
