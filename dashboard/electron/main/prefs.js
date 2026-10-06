import { existsSync, readFileSync } from 'fs'

// Small user preferences kept beside the app's other state (userData/prefs.json). Only known keys, only the
// right types; anything else is ignored so a bad edit can't change behaviour by accident.
export const DEFAULT_PREFS = {
  // The native "Merge PR?" popup after clicking Approve & Merge. Off by default: the click is the decision, a
  // second in-flight click is refused by merge_ops, and the merge gate retests before anything lands. Set
  // {"confirmMerge": true} in prefs.json to bring the popup back. (Deny/Drop always confirm: it can't be undone.)
  confirmMerge: false
}

export function readPrefs(file) {
  if (!existsSync(file)) return { ...DEFAULT_PREFS }
  try {
    const raw = JSON.parse(readFileSync(file, 'utf-8'))
    const out = { ...DEFAULT_PREFS }
    for (const [k, v] of Object.entries(DEFAULT_PREFS)) if (typeof raw[k] === typeof v) out[k] = raw[k]
    return out
  } catch {
    return { ...DEFAULT_PREFS }
  }
}
