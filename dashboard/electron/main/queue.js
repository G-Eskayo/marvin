import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

// The scanner's queue and what is running now (ADR 0053): lib/ticket_queue.py builds both, the queue from the scanner's own
// ordering and the running list from claim labels. It asks GitHub for every dispatchable project, so it is cached for a
// minute; a failed read is an error, never an empty queue.
const TTL_MS = 60000
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const CLI = path.join(homedir(), '.agents', 'lib', 'ticket_queue.py')
let cache = null

function defaultRun() {
  return new Promise((resolve, reject) =>
    execFile(PY, [CLI], { timeout: 120000 }, (err, stdout) => (err ? reject(err) : resolve(stdout)))
  )
}

export function clearQueueCache() { cache = null }

export async function getQueue({ run = defaultRun, now = Date.now() } = {}) {
  if (cache && now - cache.at < TTL_MS) return cache.value
  let value
  try {
    const r = JSON.parse(await run())
    value = { queue: r.queue || [], running: r.running || [], error: null }
  } catch (err) {
    value = { queue: [], running: [], error: `Could not read the ticket queue: ${err.message}` }
  }
  cache = { at: now, value }
  return value
}
