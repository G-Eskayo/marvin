import { execFile, spawn as nodeSpawn } from 'node:child_process'
import { homedir } from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'

// marvin#1195: restart the webhook-server when its code changes. The code-sync pulls
// origin/main into ~/.agents, and if that succeeds (no conflicts), webhook_restart.py
// is spawned to make the restart decision. Detached, so the watch loop never waits for
// the pull or restart to finish. Failures are logged; neither blocks the merge queue.
//
// To handle the settle window (webhook_restart.py waits 60s for a fresh change to settle),
// a delayed re-run of webhook_restart.py is scheduled after SETTLE_SECONDS. This ensures
// that even if the first run skips due to "too fresh", the second run will trigger when
// the change has settled.

const VENV_PYTHON = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const CODE_SYNC_SCRIPT = path.join(homedir(), '.agents', 'lib', 'code_sync.py')
const WEBHOOK_RESTART_SCRIPT = path.join(homedir(), '.agents', 'lib', 'webhook_restart.py')
const MARVIN_REPO = 'G-Eskayo/marvin'
const SETTLE_SECONDS = 60 // must match webhook_restart.py's SETTLE_SECONDS
const execFileAsync = promisify(execFile)

export function createCodeSyncCheckTrigger({ spawn = nodeSpawn, exec = execFileAsync, now = Date.now, minGapMs = 60_000 } = {}) {
  let last = -Infinity
  return async (repo) => {
    if (repo !== MARVIN_REPO) return false
    if (now() - last < minGapMs) return false
    last = now()
    try {
      await exec(VENV_PYTHON, [CODE_SYNC_SCRIPT, 'pull', path.join(homedir(), '.agents')])
    } catch (e) {
      console.error(`[code-sync-check] pull failed: ${String(e?.message || e).slice(0, 200)}`)
      return false
    }
    try {
      spawn(VENV_PYTHON, [WEBHOOK_RESTART_SCRIPT], { detached: true, stdio: 'ignore' }).unref()
      // Schedule a delayed re-check after the settle window. If the first run skipped
      // because the change is too fresh, this run will happen after it has settled.
      setTimeout(() => {
        try {
          spawn(VENV_PYTHON, [WEBHOOK_RESTART_SCRIPT], { detached: true, stdio: 'ignore' }).unref()
        } catch (e) {
          console.error(`[code-sync-check] delayed webhook-restart failed: ${String(e?.message || e)}`)
        }
      }, SETTLE_SECONDS * 1000)
    } catch (e) {
      console.error(`[code-sync-check] could not start webhook-restart: ${String(e?.message || e)}`)
      return false
    }
    return true
  }
}
