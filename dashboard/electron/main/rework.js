import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

// Where each sent-back ticket's rework stands, from lib/rework_status.py (running, queued at position N, paused and
// why, held, needs a person). It asks GitHub for the sent-back tickets, so it is cached for a minute and a failure
// means "no status", never a broken list.
const TTL_MS = 60_000
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const CLI = path.join(homedir(), '.agents', 'lib', 'rework_status.py')
let cache = null

function defaultRun() {
  return new Promise((resolve, reject) =>
    execFile(PY, [CLI, 'report'], { timeout: 60000 }, (err, stdout) => (err ? reject(err) : resolve(stdout)))
  )
}

export function clearReworkCache() { cache = null }

export async function getReworkStatus({ run = defaultRun, now = Date.now() } = {}) {
  if (cache && now - cache.at < TTL_MS) return cache.value
  let value
  try {
    value = JSON.parse(await run())
  } catch {
    value = {}
  }
  cache = { at: now, value }
  return value
}
