import { readFileSync, existsSync } from 'fs'
import { execFile } from 'child_process'
import { promisify } from 'util'

const execFileP = promisify(execFile)

// Shell out to tailscale whois to resolve a peer's identity from its IP.
// Returns the peer's node name (first label of hostname/DNS name), or null on failure.
// Failable: no Tailscale, unknown peer, whois not available.
export async function whois(ip, execFn = execFileP) {
  try {
    const { stdout } = await execFn('/Applications/Tailscale.app/Contents/MacOS/Tailscale', ['whois', '--json', ip])
    const result = JSON.parse(stdout)
    // Extract the first label of the hostname or DNS name (before the first dot).
    const hostname = result.Node?.Name || result.Node?.Hostnames?.[0] || ''
    if (!hostname) return null
    return hostname.split('.')[0]
  } catch {
    return null
  }
}

// Load the allowlist from ~/.claude/mobile-allowlist.json.
// Shape: { "devices": ["device-name", ...] }
// Returns an empty array if file doesn't exist or is malformed.
export function loadAllowlist(path) {
  if (!existsSync(path)) return []
  try {
    const data = JSON.parse(readFileSync(path, 'utf-8'))
    return data.devices || []
  } catch {
    return []
  }
}

// Case-insensitive match of peer against allowlist.
export function isAllowed(peer, allowlist) {
  if (!peer) return false
  const lowerPeer = peer.toLowerCase()
  return allowlist.some((device) => device.toLowerCase() === lowerPeer)
}
