import { spawn as nodeSpawn } from 'node:child_process'
import { homedir } from 'node:os'
import path from 'node:path'

// #443: start the installed-app rebuild check when the change watch sees G-Eskayo/marvin change -- so a merge made
// anywhere (GitHub site or app, the dashboard, another machine) reaches this Mac's app within minutes.
// lib/dashboard_rebuild.py makes the actual decision (is the app behind origin/main, settled, no build running, not a
// known-failed build); this only wakes it. Detached, so restarting this server mid-build cannot kill the build.

const VENV_PYTHON = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
export const REBUILD_CHECK_ARGS = [path.join(homedir(), '.agents', 'lib', 'dashboard_rebuild.py')]
const MARVIN_REPO = 'G-Eskayo/marvin'

export function createRebuildCheckTrigger({ spawn = nodeSpawn, now = Date.now, minGapMs = 60_000 } = {}) {
  let last = -Infinity
  return (repo) => {
    if (repo !== MARVIN_REPO) return false
    if (now() - last < minGapMs) return false // one merge is several GitHub events; one check is enough
    last = now()
    try {
      spawn(VENV_PYTHON, REBUILD_CHECK_ARGS, { detached: true, stdio: 'ignore' }).unref()
    } catch (e) {
      console.error(`[rebuild-check] could not start: ${String(e?.message || e)}`)
      return false
    }
    return true
  }
}
