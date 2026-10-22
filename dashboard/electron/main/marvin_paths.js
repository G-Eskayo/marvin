import { existsSync, mkdirSync, renameSync, cpSync, rmSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// Where MARVIN keeps its own per-machine state and caches: ~/.agents/var/ (gitignored, never synced through git).
// MARVIN owns it, so it keeps working with no Claude Code install or subscription (memory: MARVIN self-reliance,
// 2026-10-21). Nothing new goes under ~/.claude. Resolved on every call, so a test's temp HOME is honoured.
// MARVIN_VAR_DIR overrides it (tests, a second checkout).
export function marvinVarDir(env = process.env) {
  return env.MARVIN_VAR_DIR || path.join(homedir(), '.agents', 'var')
}

export const varPath = (...parts) => path.join(marvinVarDir(), ...parts)

// Moves a file or folder from its old place to its new one, once: only when the old one exists and the new one does
// not. Never overwrites, never throws (a failed move leaves the old copy, and the new place simply starts empty).
export function migrateOnce(oldPath, newPath) {
  try {
    if (!existsSync(oldPath) || existsSync(newPath)) return false
    mkdirSync(path.dirname(newPath), { recursive: true })
    try {
      renameSync(oldPath, newPath)
    } catch {
      cpSync(oldPath, newPath, { recursive: true }) // another volume: copy, then remove
      rmSync(oldPath, { recursive: true, force: true })
    }
    return true
  } catch {
    return false
  }
}
