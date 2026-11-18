import { readFileSync, existsSync } from 'fs'
import { homedir } from 'os'
import { execFileSync } from 'child_process'
import path from 'path'

// Same registry cross_machine_merge.py/machine_profile.py maintain on the
// Python side (see lib/machine_profile.py's NETWORK_PATH) -- read directly
// here so the Electron main process doesn't need a Python subprocess just
// to answer "which device am I".
export const NETWORK_PATH = path.join(homedir(), '.claude', 'marvin-network.json')

function defaultReadHardwareUuid() {
  try {
    const out = execFileSync('/usr/sbin/ioreg', ['-d2', '-c', 'IOPlatformExpertDevice'], { encoding: 'utf-8' })
    const line = out.split('\n').find((l) => l.includes('IOPlatformUUID'))
    return line ? line.split('"')[3] : ''
  } catch {
    return ''
  }
}

function loadRegistry(networkPath) {
  if (!existsSync(networkPath)) return {}
  try {
    return JSON.parse(readFileSync(networkPath, 'utf-8')).devices || {}
  } catch {
    return {}
  }
}

// Mirrors machine_profile.py's registry_id(): matched by hardware UUID, not
// hostname/label, so a rename or a second same-kind machine can't misidentify
// this one.
export function resolveDeviceId(readHardwareUuid = defaultReadHardwareUuid, networkPath = NETWORK_PATH) {
  const myUuid = readHardwareUuid()
  if (!myUuid) return null
  const registry = loadRegistry(networkPath)
  for (const [deviceId, info] of Object.entries(registry)) {
    if (info.hardware_uuid === myUuid) return deviceId
  }
  return null
}

// ADR 0032's primary automation host -- the registry's "desktop"-kind
// device, not a hardcoded id, so this still resolves if mac-mini-1 is ever
// renamed or replaced.
export function primaryHostTailscaleName(networkPath = NETWORK_PATH) {
  const id = primaryDeviceId(networkPath)
  return id ? loadRegistry(networkPath)[id].tailscale_hostname || null : null
}

// The primary's registry id ("mac-mini-1"), for naming it in words (marvin#762). Same pick as above: the first
// "desktop"-kind device.
export function primaryDeviceId(networkPath = NETWORK_PATH) {
  const registry = loadRegistry(networkPath)
  for (const [id, info] of Object.entries(registry)) {
    if (info?.kind === 'desktop') return id
  }
  return null
}

export function isPrimaryHost(readHardwareUuid = defaultReadHardwareUuid, networkPath = NETWORK_PATH) {
  const registry = loadRegistry(networkPath)
  const myId = resolveDeviceId(readHardwareUuid, networkPath)
  return myId != null && registry[myId]?.kind === 'desktop'
}

// The default host for this machine's outbound calls to the MR-approval
// webhook (ADR 0032): itself when it is the primary host, otherwise the
// primary host's Tailscale hostname. Explicit MARVIN_* env vars still take
// precedence over this -- see electron/main/index.js.
export function resolveServiceDefaults(readHardwareUuid = defaultReadHardwareUuid, networkPath = NETWORK_PATH) {
  if (isPrimaryHost(readHardwareUuid, networkPath)) {
    return { host: 'localhost' }
  }
  const hostname = primaryHostTailscaleName(networkPath)
  return { host: hostname || 'localhost' }
}

// Every other registered Mac and its Tailscale name, for reads from their webhook servers (#612, as GET /sessions
// does for #331). No hardware UUID means "unknown which one is me": every device is listed.
export function peerHosts(readHardwareUuid = defaultReadHardwareUuid, networkPath = NETWORK_PATH) {
  const registry = loadRegistry(networkPath)
  const me = resolveDeviceId(readHardwareUuid, networkPath)
  return Object.entries(registry)
    .filter(([id, info]) => id !== me && info && info.tailscale_hostname)
    .map(([id, info]) => ({ id, host: info.tailscale_hostname }))
}

// Check if a hostname is a registered Mac (case-insensitive). Returns true only when the hostname
// matches a registered device's tailscale_hostname and that device's OS is macOS.
// Mirrors machine_profile.py's remote_macs() documented rule: only macOS devices are trusted.
export function isRegisteredMacHostname(hostname, networkPath = NETWORK_PATH) {
  if (!hostname || typeof hostname !== 'string') return false
  const registry = loadRegistry(networkPath)
  const lowerHostname = hostname.toLowerCase()
  for (const [id, info] of Object.entries(registry)) {
    if (!info || !info.tailscale_hostname) continue
    if (info.tailscale_hostname.toLowerCase() === lowerHostname) {
      return (info.os || 'macos') === 'macos'
    }
  }
  return false
}
