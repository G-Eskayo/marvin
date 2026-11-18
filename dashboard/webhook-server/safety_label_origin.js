import { allowedPeerAddress } from './merge_stage_relay.js'
import { isRegisteredMacHostname } from '../electron/main/device_identity.js'

// Default whois function: shell out to Tailscale to resolve an IP to its hostname.
// Returns the peer's node name (first label of hostname), or null on failure.
async function defaultWhois(ip) {
  const { execFile } = await import('child_process')
  const { promisify } = await import('util')
  const execFileP = promisify(execFile)
  try {
    const { stdout } = await execFileP('/Applications/Tailscale.app/Contents/MacOS/Tailscale', ['whois', '--json', ip])
    const result = JSON.parse(stdout)
    const hostname = result.Node?.Name || result.Node?.Hostnames?.[0] || ''
    if (!hostname) return null
    return hostname.split('.')[0]
  } catch {
    return null
  }
}

// Check if a remote address is from a registered Mac. Returns true only when:
// - The address is loopback (127.0.0.1 or ::1), OR
// - The address is in allowedPeerAddress range (Tailscale range) AND resolves to a registered Mac hostname.
// Returns false if not in allowedPeerAddress range (no shell out), or if whois/registry lookup fails.
// Fails closed on any error: returns false rather than crashing.
export async function isMacOrigin(
  remoteAddress,
  {
    whoisFn = defaultWhois,
    isMacHostname = isRegisteredMacHostname,
  } = {}
) {
  const a = String(remoteAddress || '').replace(/^::ffff:/, '')

  // Loopback is always trusted.
  if (a === '127.0.0.1' || a === '::1') return true

  // Not in Tailscale range: reject without shell out.
  if (!allowedPeerAddress(a)) return false

  // Resolve the IP to a hostname and check if it's a registered Mac.
  try {
    const hostname = await whoisFn(a)
    if (!hostname) return false
    return isMacHostname(hostname)
  } catch {
    // Fail closed: if anything goes wrong, reject the request.
    return false
  }
}
