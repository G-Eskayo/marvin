import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { dirname } from 'path'

// Persists build status and what has been shown to the user, so the update banner
// can decide whether to notify and auto-restart.
//
// Ready file (~/.claude/logs/dashboard-build-ready.json): written by rebuild_and_install.sh
// once the final build installs successfully. { sha, installedAt }.
//
// Shown file (userData/build-ready-shown.json): tracks the last SHA for which the user
// was notified and what action they took (later, restart). Used to avoid re-showing the
// banner every time the app restarts if the user already saw it.

export function readReady(file) {
  if (!existsSync(file)) return null
  try {
    const data = JSON.parse(readFileSync(file, 'utf-8'))
    return { sha: data.sha || null, installedAt: data.installedAt || null }
  } catch {
    return null
  }
}

export function readShown(file) {
  if (!existsSync(file)) return {}
  try {
    const data = JSON.parse(readFileSync(file, 'utf-8'))
    return data || {}
  } catch {
    return {}
  }
}

export function writeShown(file, sha) {
  const existing = readShown(file)
  const updated = { ...existing, lastShownSha: sha, lastShownAt: Date.now() }
  mkdirSync(dirname(file), { recursive: true })
  writeFileSync(file, JSON.stringify(updated))
}

// Pure decision functions for the banner and app restart logic.

export function shouldNotify(ready, shown) {
  // Show the banner if a new build is ready that we haven't yet notified for.
  if (!ready || !ready.sha) return false
  return ready.sha !== shown.lastShownSha
}

export function shouldShowOnceToast(ready, shown) {
  // The first time the banner appears, show a toast. After that, it's just a persistent banner.
  if (!shouldNotify(ready, shown)) return false
  return !shown.lastShownAt || shown.lastShownAt === undefined
}

export function shouldAutoRestart(ready, shown, appJustGainedFocus) {
  // Auto-restart if the user took no action (clicked "Later" or ignored the banner)
  // and the app just gained focus. This is a gentle UX: restart when they come back.
  if (!ready || !ready.sha) return false
  if (!appJustGainedFocus) return false
  // If this is a new update (not shown yet), don't auto-restart; let the banner be seen first.
  if (ready.sha !== shown.lastShownSha) return false
  // If they explicitly clicked 'restart', we're done (the restart already happened).
  // If they clicked 'later', auto-restart on next focus (they deferred, now we're back).
  if (shown.action === 'restart') return false
  return true
}
