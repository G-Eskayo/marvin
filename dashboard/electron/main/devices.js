import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

// One row per registered device (idle / busy+task / unreachable), asked of lib/device_status.py, which
// reuses task_dispatch's readers. The remote check is an SSH round-trip, so it is cached for a few seconds.
const TTL_MS = 8000
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const CLI = path.join(homedir(), '.agents', 'lib', 'device_status.py')
let cache = null

function defaultRun() {
  return new Promise((resolve, reject) =>
    execFile(PY, [CLI], { timeout: 45000 }, (err, stdout) => (err ? reject(err) : resolve(stdout)))
  )
}

export function clearDeviceCache() { cache = null }

export async function getDeviceStatuses({ run = defaultRun, now = Date.now() } = {}) {
  if (cache && now - cache.at < TTL_MS) return cache.value
  let value
  try {
    value = { devices: JSON.parse(await run()), error: null }
  } catch (err) {
    value = { devices: [], error: `Could not read device status: ${err.message}` }
  }
  cache = { at: now, value }
  return value
}
