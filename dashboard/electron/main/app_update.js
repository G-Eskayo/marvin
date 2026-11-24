import { app, ipcMain, dialog } from 'electron'
import { join, dirname, basename } from 'path'
import { existsSync, readFileSync, writeFileSync, renameSync, statSync, mkdirSync } from 'fs'
import { homedir } from 'os'

const DEMO_HOLD_FILE = join(homedir(), '.claude', 'logs', 'dashboard-demo-hold')
const UPDATE_MARKER_FILE = join(homedir(), '.claude', 'logs', 'dashboard-announced-update')
const STAGED_APP_PATH = '/Applications/MARVIN.app.staged'
const LIVE_APP_PATH = '/Applications/MARVIN.app'

function shouldAutoRestart({ idleS, bound }) {
  return idleS >= bound
}

function planSwap() {
  const live = { path: LIVE_APP_PATH, exists: existsSync(LIVE_APP_PATH) }
  const staged = { path: STAGED_APP_PATH, exists: existsSync(STAGED_APP_PATH) }
  if (!staged.exists) return null
  return { live, staged }
}

async function atomicSwap(mainWindow) {
  const swap = planSwap()
  if (!swap) return { ok: false, reason: 'no staged build' }

  try {
    // Verify the staged bundle before swapping
    const { execFile } = await import('child_process')
    const { promisify } = await import('util')
    const { readdirSync, rmSync } = await import('fs')
    const execFileAsync = promisify(execFile)

    try {
      await execFileAsync('codesign', ['--verify', '--deep', '--strict', swap.staged.path])
    } catch (err) {
      return { ok: false, reason: `staged bundle signature invalid: ${err.message}` }
    }

    // Delete old backups before creating a new one (unbounded growth prevention, ADR 0065)
    try {
      const appDir = dirname(LIVE_APP_PATH)
      const baseName = basename(LIVE_APP_PATH)
      const files = readdirSync(appDir)
      files.forEach((f) => {
        if (f.startsWith(`${baseName}.old.`)) {
          rmSync(join(appDir, f), { recursive: true, force: true })
        }
      })
    } catch (err) {
      console.warn('[app-update] could not clean old backups:', err.message)
    }

    // Two-step atomic swap: move live away, move staged in place
    const timestamp = Math.floor(Date.now() / 1000)
    const backup = `${LIVE_APP_PATH}.old.${timestamp}`

    if (swap.live.exists) {
      renameSync(swap.live.path, backup)
    }
    renameSync(swap.staged.path, swap.live.path)

    // Clean up the backup we just created since the swap succeeded
    try {
      rmSync(backup, { recursive: true, force: true })
    } catch (err) {
      console.warn('[app-update] could not remove backup after swap:', err.message)
    }

    return { ok: true }
  } catch (err) {
    return { ok: false, reason: err.message }
  }
}

export function registerAppUpdateHandlers({ mainWindow: getMainWindow }) {
  ipcMain.handle('app:getDemoHold', () => {
    return existsSync(DEMO_HOLD_FILE)
  })

  ipcMain.handle('app:setDemoHold', (_event, enabled) => {
    if (enabled) {
      mkdirSync(dirname(DEMO_HOLD_FILE), { recursive: true })
      writeFileSync(DEMO_HOLD_FILE, '')
      // Cancel any pending idle restart when demo hold is enabled
      if (idleTimer) {
        clearTimeout(idleTimer)
        idleTimer = null
        idleStartedAt = null
      }
      pendingUpdate = null
    } else {
      if (existsSync(DEMO_HOLD_FILE)) {
        import('fs').then(({ unlinkSync }) => {
          try { unlinkSync(DEMO_HOLD_FILE) } catch {}
        })
      }
    }
  })

  let pendingUpdate = null
  let idleTimer = null
  let idleStartedAt = null
  const idleBound = 60 // 60 seconds of idle to trigger auto-restart

  function getDemoHold() {
    return existsSync(DEMO_HOLD_FILE)
  }

  function armIdleTimer() {
    // Clear any existing timer and blur listener
    if (idleTimer) clearTimeout(idleTimer)
    idleStartedAt = null
    idleTimer = null

    const mainWindow = getMainWindow()
    if (!pendingUpdate || !mainWindow) return

    // Set up a one-shot blur listener (not re-arming)
    const onBlur = () => {
      idleStartedAt = Date.now()
      // Check idle once; arm timer only if not ready yet
      checkIdle()
    }

    // Also set up a focus listener to cancel the pending restart
    const onFocus = () => {
      if (idleTimer) clearTimeout(idleTimer)
      idleTimer = null
      idleStartedAt = null
    }

    mainWindow.once('blur', onBlur)
    mainWindow.on('focus', onFocus)

    const checkIdle = () => {
      const now = Date.now()
      const idleS = Math.floor((now - (idleStartedAt || now)) / 1000)
      if (shouldAutoRestart({ idleS, bound: idleBound })) {
        performRestart()
      } else {
        // Schedule next check (not a polling loop, just one continuation)
        idleTimer = setTimeout(checkIdle, 5000)
      }
    }

    // If window is already blurred, start checking now
    if (!mainWindow.isFocused?.()) {
      idleStartedAt = Date.now()
      checkIdle()
    }
  }

  async function performRestart() {
    if (idleTimer) clearTimeout(idleTimer)
    if (!pendingUpdate || getDemoHold()) return

    const mainWindow = getMainWindow()
    const swap = await atomicSwap(mainWindow)
    if (!swap.ok) {
      console.error('[app-update] swap failed:', swap.reason)
      pendingUpdate = null
      return
    }

    // Write update marker before restart
    try {
      mkdirSync(dirname(UPDATE_MARKER_FILE), { recursive: true })
      writeFileSync(UPDATE_MARKER_FILE, pendingUpdate.sha || 'unknown')
    } catch (err) {
      console.error('[app-update] could not write marker:', err.message)
    }

    app.relaunch()
    app.exit(0)
  }

  ipcMain.handle('app:restartForUpdate', async () => {
    if (!pendingUpdate) return { ok: false, reason: 'no pending update' }
    await performRestart()
  })

  ipcMain.handle('app:lastUpdate', () => {
    try {
      const marker = readFileSync(UPDATE_MARKER_FILE, 'utf8').trim()
      return { sha: marker }
    } catch {
      return null
    }
  })

  // Notify renderer that an update is ready
  function notifyUpdateReady(sha) {
    pendingUpdate = { sha, announcedAt: Date.now() }
    const mainWindow = getMainWindow()
    mainWindow?.webContents.send('app:updateReady', { sha })
    armIdleTimer()
  }

  // Handle refresh server messages
  return { notifyUpdateReady }
}

export function handleRefreshServerUpdate(payload, mainWindow, appUpdateHandlers) {
  // Already dispatched by topic in index.js, so we know it's an update topic.
  // Record this SHA as the pending one and notify the app.
  appUpdateHandlers.notifyUpdateReady(payload.sha || 'unknown')
}
