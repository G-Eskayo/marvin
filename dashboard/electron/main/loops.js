import { homedir } from 'os'
import path from 'path'

// Vitals > Loops (marvin#1123, ADR 0083): every feedback loop's status from lib/loops.py (the registry's only reader),
// and its one fix. The renderer passes only a loop id; what runs comes from config/loops.json, never from here.
const HOME = homedir()
const PY = path.join(HOME, '.agents', 'venv', 'bin', 'python')
const LOOPS = path.join(HOME, '.agents', 'lib', 'loops.py')
export const LOOP_ID = /^[a-z0-9][a-z0-9-]{0,47}$/

function parse(stdout) {
  const d = JSON.parse(String(stdout || ''))
  if (!d || typeof d !== 'object') throw new Error('no answer')
  return d
}

export function createLoops({ execFile, renew = null, py = PY, script = LOOPS } = {}) {
  return {
    async status() {
      try {
        const { stdout } = await execFile(py, [script, 'status'], { timeout: 30_000 })
        return parse(stdout)
      } catch (err) {
        return { loops: [], counts: null, problems: [], problem: String(err?.message || err).split('\n')[0].slice(0, 200) }
      }
    },
    // One loop's fix. A re-login goes to the Accounts renew flow that already exists; opening a ticket is handed back
    // to the renderer, which opens it inside the dashboard.
    async fix(id) {
      if (typeof id !== 'string' || !LOOP_ID.test(id)) return { ok: false, error: 'unknown loop' }
      let out
      try {
        const { stdout } = await execFile(py, [script, 'fix', id], { timeout: 150_000 })
        out = parse(stdout)
      } catch (err) {
        try { out = parse(err?.stdout) } catch { return { ok: false, error: String(err?.message || err).split('\n')[0].slice(0, 200) } }
      }
      if (out?.ok && out.how === 'renew' && renew) {
        try {
          const r = await renew(String(out.account))
          return { ok: true, how: 'renew', says: r?.started ? `Renewing in its own tab` : r?.command ? `Run on ${r.where}: ${r.command}` : 'Renew started' }
        } catch (err) {
          return { ok: false, how: 'renew', error: String(err?.message || err).slice(0, 200) }
        }
      }
      return out
    }
  }
}
