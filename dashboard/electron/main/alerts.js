import { homedir } from 'os'
import path from 'path'

// Vitals > "Can MARVIN reach you?" (marvin#1123, ADR 0083): the last alerts the one alert path sent and what each
// channel really did, read through lib/mr_notification.py (the only reader of its run log), and a test alert. The
// renderer chooses nothing: both calls are fixed argv.
const HOME = homedir()
const PY = path.join(HOME, '.agents', 'venv', 'bin', 'python')
const MN = path.join(HOME, '.agents', 'lib', 'mr_notification.py')

function parse(stdout) {
  const d = JSON.parse(String(stdout || ''))
  if (!d || typeof d !== 'object') throw new Error('no answer')
  return d
}

export function createAlerts({ execFile, py = PY, script = MN } = {}) {
  return {
    async status() {
      try {
        const { stdout } = await execFile(py, [script, 'reach'], { timeout: 15_000 })
        return parse(stdout)
      } catch (err) {
        return { verdict: 'unknown', last: null, recent: [], problem: String(err?.message || err).split('\n')[0].slice(0, 200) }
      }
    },
    // Sends one real alert on every channel. A non-zero exit means nothing was delivered; its JSON still says why.
    async test() {
      try {
        const { stdout } = await execFile(py, [script, 'test'], { timeout: 20_000 })
        return parse(stdout)
      } catch (err) {
        try { return parse(err?.stdout) } catch { /* no JSON: report the error itself */ }
        return { delivered: [], channels: {}, problem: String(err?.message || err).split('\n')[0].slice(0, 200) }
      }
    }
  }
}
