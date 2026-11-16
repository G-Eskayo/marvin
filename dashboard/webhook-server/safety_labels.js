// The safety monitor's one calibration lives on the primary host (decided 2026-10-26). Other Macs deliver review
// answers here and read back the tau map, over the same webhook server and Tailscale route the dashboard already uses
// for Approve. Nothing is checked or stored in JS: skills/safety-monitor/scripts/calibrate.py validates every field
// (loop name, score, label, note, entry hash) and refuses a bad one; a duplicate entry hash is ignored there.
//   POST /safety/label  {loop, score, label, note?, entry_id?, source?}  ->  {ok, recorded, taus} | {ok:false, error}
//   GET  /safety/taus                                          ->  {"*": tau, loop: tau, ...}
//
// Ticket #927: POST /safety/label is gated to registered macOS peers only (via isMacPeer, which uses Tailscale
// whois to resolve the peer's hostname and checks against the registry). Manual reviews from Macs carry source="person"
// and override any prior auto-generated labels for the same entry (first-wins for non-person otherwise).

import { whois } from '../mobile-backend/device_gate.js'
import { macHostnames } from '../electron/main/device_identity.js'

export const SAFETY_MAX_BODY = 16 * 1024

// Ticket #927: check whether an IP is from a registered macOS peer (for /safety/label gate).
// Loopback short-circuits, else whois + registry match.
export async function isMacPeer(ip, { whoisFn = whois, macHostnamesFn = macHostnames } = {}) {
  if (!ip) return false
  if (ip === '127.0.0.1' || ip === '::1' || ip === 'localhost') return true
  try {
    const hostname = await whoisFn(ip)
    if (!hostname) return false
    const macHosts = macHostnamesFn()
    return macHosts.has(hostname.toLowerCase())
  } catch {
    return false
  }
}

// run(args) -> stdout of `python calibrate.py ...args` (index.js). Returns { status, json }.
export async function handleSafetyRequest({ method, url, body }, run) {
  if (method === 'GET' && url === '/safety/taus') {
    try {
      return { status: 200, json: JSON.parse(await run(['taus'])) }
    } catch (err) {
      return { status: 500, json: { ok: false, error: String(err?.message || err) } }
    }
  }
  if (method !== 'POST' || url !== '/safety/label') return { status: 404, json: { ok: false, error: 'not found' } }
  let payload
  try {
    payload = JSON.parse(String(body || ''))
  } catch {
    return { status: 400, json: { ok: false, error: 'Body must be a JSON object' } }
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return { status: 400, json: { ok: false, error: 'Body must be a JSON object' } }
  // Only the known fields travel on, as one argv item (execFile, no shell).
  const label = Object.fromEntries(['loop', 'score', 'label', 'note', 'entry_id', 'source'].filter((k) => k in payload).map((k) => [k, payload[k]]))
  let stdout
  try {
    stdout = await run(['record', JSON.stringify(label)])
  } catch (err) {
    // calibrate.py exits 1 with {"ok": false, "error"} for an invalid label: that is the caller's mistake, not ours.
    const out = String(err?.stdout || '')
    try {
      const parsed = JSON.parse(out)
      if (parsed && parsed.ok === false) return { status: 422, json: parsed }
    } catch { /* fall through */ }
    return { status: 500, json: { ok: false, error: String(err?.message || err) } }
  }
  try {
    return { status: 200, json: JSON.parse(stdout) }
  } catch {
    return { status: 500, json: { ok: false, error: 'no result' } }
  }
}
