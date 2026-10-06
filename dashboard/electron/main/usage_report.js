import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

// The Metrics tab's tool and token usage for BOTH machines, built by lib/usage_report.py (this machine's scans plus the other
// machine's read over ssh). Building it can take several seconds (a scan, an ssh round-trip), so the result is cached for a minute
// and simultaneous callers share one build. A failed build keeps the last good report and says what went wrong.
const TTL_MS = 60_000
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const CLI = path.join(homedir(), '.agents', 'lib', 'usage_report.py')
let cache = null
let inflight = null

function defaultRun() {
  return new Promise((resolve, reject) =>
    execFile(PY, [CLI], { timeout: 180_000, maxBuffer: 50 * 1024 * 1024 }, (err, stdout) => (err ? reject(err) : resolve(stdout)))
  )
}

export function clearUsageCache() { cache = null; inflight = null }

export async function getUsageReport({ run = defaultRun, now = Date.now() } = {}) {
  if (cache && now - cache.at < TTL_MS) return { report: cache.report, error: null }
  if (!inflight) {
    inflight = (async () => {
      try {
        const report = JSON.parse(await run())
        if (!Array.isArray(report?.machines)) throw new Error('not a usage report')
        cache = { at: now, report }
        return { report, error: null }
      } catch (err) {
        const why = err instanceof SyntaxError || /not a usage report/.test(err.message) ? 'Could not read the usage report' : `Could not build the usage report: ${err.message}`
        return { report: cache?.report ?? null, error: why }
      } finally {
        inflight = null
      }
    })()
  }
  return inflight
}
