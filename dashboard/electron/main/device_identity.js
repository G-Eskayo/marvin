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
  const registry = loadRegistry(networkPath)
  for (const info of Object.values(registry)) {
    if (info.kind === 'desktop') return info.tailscale_hostname || null
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
