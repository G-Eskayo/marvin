import http from 'http'
import { listHelpers, sortHelpers } from '../../webhook-server/chat_helpers.js'
import { isHelperDismissed } from './helpers_dismissed.js'

// Chat helpers on this Mac and the others (#612): this Mac's from its run logs (pushed: the jobs folder is watched),
// each other Mac's from its webhook server's GET /helpers, the same channel GET /sessions uses (#331).
export const REMOTE_TTL_MS = 10000 // read-through cache bound on the LAN read; no timer of its own
const REMOTE_TIMEOUT_MS = 1500
const MAX_BYTES = 512 * 1024
const DEFAULT_CRASHED_MAX_AGE_MS = 24 * 60 * 60 * 1000 // 24 hours
const DEFAULT_CAP = 10

export function fetchHelpersFrom(host, { port = 7878, timeoutMs = REMOTE_TIMEOUT_MS } = {}) {
  return new Promise((resolve) => {
    let answered = false
    const done = (v) => {
      if (!answered) {
        answered = true
        resolve(v)
      }
    }
    const req = http.get({ host, port, path: '/helpers', timeout: timeoutMs }, (res) => {
      if (res.statusCode !== 200) {
        res.resume()
        return done(null)
      }
      let body = ''
      res.setEncoding('utf8')
      res.on('data', (c) => {
        body += c
        if (body.length > MAX_BYTES) {
          done(null)
          req.destroy()
        }
      })
      res.on('end', () => {
        try {
          const h = JSON.parse(body).helpers
          done(Array.isArray(h) ? h : null)
        } catch {
          done(null)
        }
      })
      res.on('close', () => done(null))
    })
    req.on('timeout', () => {
      done(null)
      req.destroy()
    })
    req.on('error', () => done(null))
  })
}

// Only what the row shows survives from another Mac; anything else it sends is dropped.
const STATUSES = new Set(['running', 'crashed', 'failed', 'done'])
function sanitize(h, machine) {
  if (!h || typeof h !== 'object' || !STATUSES.has(h.status) || typeof h.id !== 'string') return null
  return { ...h, machine: h.machine || machine, kind: 'helper' }
}

// Filter helpers for the home list: drop dismissed ones, expire old crashed ones, cap the remainder.
// Running helpers are never capped/dropped; they stay visible until they finish.
export function filterForHome(helpers, { dismissed, now, maxAgeMs = DEFAULT_CRASHED_MAX_AGE_MS, cap = DEFAULT_CAP } = {}) {
  const key = (h) => `${h.machine}:${h.id}`
  const active = helpers.filter((h) => {
    if (isHelperDismissed(key(h), dismissed)) return false
    if (h.status === 'crashed') {
      // For a crashed helper, use the most recent run's latest sign of life.
      // If still running, use its start time; if finished, use the finish time.
      const lastSeen = h.job?.current?.startedAt ? Date.parse(h.job.current.startedAt) : h.job?.last?.finishedAt ? Date.parse(h.job.last.finishedAt) : now
      if (isNaN(lastSeen) || now - lastSeen > maxAgeMs) return false
    }
    return true
  })
  const running = active.filter((h) => h.status === 'running')
  const other = active.filter((h) => h.status !== 'running')
  return [...running, ...other.slice(0, Math.max(0, cap - running.length))]
}

export function createHelpersReader({ listLocal = () => listHelpers(), peers = () => [], fetchRemote = fetchHelpersFrom, clock = () => Date.now(), dismissed = () => new Map() } = {}) {
  const cache = new Map()
  return async function readHelpers() {
    const local = listLocal()
    const remote = await Promise.all(
      peers().map(async ({ id, host }) => {
        const hit = cache.get(id)
        if (hit && clock() - hit.at < REMOTE_TTL_MS) return hit
        const got = await fetchRemote(host)
        const entry = { id, at: clock(), helpers: got, ok: got !== null }
        cache.set(id, entry)
        return entry
      })
    )
    const fromPeers = remote.flatMap((r) => (r.helpers || []).map((h) => sanitize(h, r.id)).filter(Boolean))
    const all = sortHelpers([...local, ...fromPeers])
    const dismissedSet = typeof dismissed === 'function' ? dismissed() : dismissed
    const filtered = filterForHome(all, { dismissed: dismissedSet, now: clock() })
    return { helpers: filtered, unreachable: remote.filter((r) => !r.ok).map((r) => r.id) }
  }
}
