import { execFile } from 'child_process'
import { readFileSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { supportRole } from '../electron/main/support.js'
import { instanceDir } from '../electron/main/instance.js'

// Support link (ADR 0073), webhook-server side. The instance file is re-read on each call (it's tiny), so a support
// block added while the server runs is picked up without a restart.
export function supportRepos(read = () => readFileSync(path.join(instanceDir(), 'instance.json'), 'utf8')) {
  try {
    return supportRole(JSON.parse(read())).repos
  } catch {
    return []
  }
}

// One `support.py sync --attempt` at a time: a change that lands while one runs queues exactly one more run, so
// a burst of changes costs two syncs, never one per change, and nothing is missed.
export function createSupportSync({ run = execFile, log = console.log } = {}) {
  const py = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
  const cli = path.join(homedir(), '.agents', 'lib', 'support.py')
  let running = false
  let again = false
  const start = (source) => {
    running = true
    run(py, [cli, 'sync', '--attempt'], { timeout: 900000 }, (err, stdout) => {
      log(`[support] sync after ${source}: ${err ? `failed: ${err.message}` : String(stdout).trim().split('\n').pop()}`)
      running = false
      if (again) {
        again = false
        start('queued change')
      }
    })
  }
  return (source) => {
    if (running) again = true
    else start(source)
  }
}

// Who watches the support repos on this Mac. A helper's webhook server (always running under launchd) watches, so the
// helper's MARVIN answers even with the dashboard closed. A helped install may not run that server at all, so its
// dashboard watches while it is open: nothing there needs to happen while nobody is looking.
export const supportWatcher = (role) => (role === 'helper' ? 'webhook' : role === 'helped' ? 'app' : null)

// The dashboard's watch on a helped install: the same change detector, authenticated with the person's own gh login
// (their support repo is private), a sync at startup, then one per change.
export function startAppSupportWatch({ repos, token, startChangeWatch, createGithubProbe, sync = createSupportSync() }) {
  sync('app start')
  return startChangeWatch({
    getRepos: repos,
    probe: createGithubProbe(token ? { GH_TOKEN: token } : {}),
    ping: (repo) => sync(repo)
  })
}
