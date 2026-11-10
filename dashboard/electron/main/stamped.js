// Stamped copies, the JS twin of lib/stamped.py (marvin#1223). Every per-Mac file carries the github feed's flat
// envelope (host, hardware_uuid, generated_at, alive_at, tolerance_s) on its own JSON object, so a screen can say which
// Mac made it and how old it is, and a frozen copy can never pass as current. Both readers run
// dashboard/test/fixtures/stamped_cases.json. Age is on this Mac's clock from the newer of generated_at/alive_at, never
// negative; a file with no stamp is "legacy" (dated by its generated_at or mtime); exactly at tolerance is not stale;
// no file or not a JSON object is "missing". Never throws.
import { readFileSync, statSync } from 'fs'

function toMs(v) {
  if (typeof v === 'boolean' || v == null) return null
  if (typeof v === 'number') return Number.isFinite(v) ? (v > 1e11 ? v : v * 1000) : null
  if (typeof v === 'string') {
    const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : `${v}Z`
    const t = Date.parse(iso)
    return Number.isNaN(t) ? null : t
  }
  return null
}

export function fromData(data, { now = Date.now(), defaultToleranceS = 600, mtimeMs = null, path = null } = {}) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return { value: null, missing: true, stale: true, ageS: null, path }
  const legacy = !data.host
  const tol = Number.isInteger(data.tolerance_s) && data.tolerance_s > 0 ? data.tolerance_s : defaultToleranceS
  let times = [toMs(data.generated_at), toMs(data.alive_at)].filter((t) => t != null)
  if (!times.length && legacy && mtimeMs != null) times = [mtimeMs]
  const base = { value: data, host: data.host || null, hardware_uuid: data.hardware_uuid || null, toleranceS: tol, legacy, missing: false, path }
  if (!times.length) return { ...base, ageS: null, stale: true, future: false }
  const raw = (now - Math.max(...times)) / 1000
  const ageS = Math.max(0, Math.round(raw))
  return { ...base, ageS, stale: ageS > tol, future: raw < 0 }
}

export function readStamped(path, { now = Date.now(), defaultToleranceS = 600 } = {}) {
  let data, mtimeMs
  try {
    data = JSON.parse(readFileSync(path, 'utf8'))
    mtimeMs = statSync(path).mtimeMs
  } catch {
    return { value: null, missing: true, stale: true, ageS: null, path }
  }
  return fromData(data, { now, defaultToleranceS, mtimeMs, path })
}

export function producerOf(copy, registry = {}) {
  if (copy?.hardware_uuid) {
    const want = String(copy.hardware_uuid).toUpperCase()
    for (const [dev, info] of Object.entries(registry || {})) if (String(info?.hardware_uuid || '').toUpperCase() === want) return dev
  }
  return copy?.host || null
}

function ago(s) {
  if (s == null) return 'age unknown'
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 2 * 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} days ago`
}

export function describeCopy(copy, registry = {}, { thisMac = null } = {}) {
  if (!copy || copy.missing) return 'no data yet'
  const dev = producerOf(copy, registry)
  const who = dev == null ? (thisMac ? 'this Mac (unstamped)' : 'an unknown Mac (unstamped)') : registry?.[dev]?.label || dev
  return `${who}, as of ${ago(copy.ageS)}${copy.stale ? ' · stale' : ''}`
}

export function newerCopy(a, b) {
  if (!a || a.missing || a.ageS == null) return b && !b.missing ? b : a
  if (!b || b.missing || b.ageS == null) return a
  return a.ageS <= b.ageS ? a : b
}
