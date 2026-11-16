// The safety monitor's one calibration lives on the primary host (decided 2026-10-26). Other Macs deliver review
// answers here and read back the tau map, over the same webhook server and Tailscale route the dashboard already uses
// for Approve. Nothing is checked or stored in JS: skills/safety-monitor/scripts/calibrate.py validates every field
// (loop name, score, label, note, entry hash) and refuses a bad one; a duplicate entry hash is ignored there.
//   POST /safety/label  {loop, score, label, note?, entry_id?}  ->  {ok, recorded, taus} | {ok:false, error}
//   GET  /safety/taus                                          ->  {"*": tau, loop: tau, ...}

export const SAFETY_MAX_BODY = 16 * 1024

// Resolve the source of a safety label submission: 'loopback' for localhost, otherwise matched against
// registered Macs via whois + isAllowed. Returns 'loopback', a Tailscale hostname, or null if not a registered Mac.
export async function safetyLabelSource(remoteAddress, { whois, macHosts, isAllowed }) {
  if (!remoteAddress) return null
  // Loopback always allowed (same machine).
  if (remoteAddress === '127.0.0.1' || remoteAddress === '::1' || remoteAddress.startsWith('::ffff:127.0.0.1')) {
    return 'loopback'
  }
  // Extract IP for IPv6-mapped addresses.
  const ip = remoteAddress.startsWith('::ffff:') ? remoteAddress.slice(7) : remoteAddress
  // Resolve via whois and match against registered Macs.
  const peer = await whois(ip)
  const hosts = macHosts()
  if (peer && isAllowed(peer, hosts)) return peer
  return null
}

// run(args) -> stdout of `python calibrate.py ...args` (index.js). Returns { status, json }.
export async function handleSafetyRequest({ method, url, body, source } = {}, run) {
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
  // Only the known fields travel on, as one argv item (execFile, no shell). Client-supplied source is discarded.
  const label = Object.fromEntries(['loop', 'score', 'label', 'note', 'entry_id'].filter((k) => k in payload).map((k) => [k, payload[k]]))
  // Add the verified source if it exists.
  if (source) {
    label.source = source
  }
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
