import http from 'http'
import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'
import { listHelpers, sortHelpers, HELPER_ID } from '../../webhook-server/chat_helpers.js'

// Chat helpers on this Mac and the others (#612): this Mac's from its run logs (pushed: the jobs folder is watched),
// each other Mac's from its webhook server's GET /helpers, the same channel GET /sessions uses (#331).
export const REMOTE_TTL_MS = 10000 // read-through cache bound on the LAN read; no timer of its own
const REMOTE_TIMEOUT_MS = 1500
const MAX_BYTES = 512 * 1024
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const CLI = path.join(homedir(), '.agents', 'lib', 'chat_helpers.py')

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

export function dismissLocalHelper(id, { run = execFile } = {}) {
  return new Promise((resolve) => {
    const aid = String(id || '').replace(/^helper-/, '')
    if (!HELPER_ID.test(`helper-${aid}`)) {
      resolve({ ok: false, error: 'invalid helper id' })
      return
    }
    run(PY, [CLI, 'dismiss', aid], { timeout: 5000 }, (err, stdout, stderr) => {
      try {
        const parsed = JSON.parse(String(stdout).trim().split('\n').pop())
        if (typeof parsed === 'object' && parsed !== null) {
          resolve(parsed)
        } else {
          resolve({ ok: false, error: 'invalid response' })
        }
      } catch {
        resolve({ ok: false, error: (stderr || err?.message || 'dismiss failed').slice(0, 300) })
      }
    })
  })
}

// Only what the row shows survives from another Mac; anything else it sends is dropped.
const STATUSES = new Set(['running', 'crashed', 'failed', 'done'])
function sanitize(h, machine) {
  if (!h || typeof h !== 'object' || !STATUSES.has(h.status) || typeof h.id !== 'string') return null
  return { ...h, machine: h.machine || machine, kind: 'helper' }
}

export function createHelpersReader({ listLocal = () => listHelpers(), peers = () => [], fetchRemote = fetchHelpersFrom, clock = () => Date.now() } = {}) {
  const cache = new Map()
  const forgetCache = (peerId) => cache.delete(peerId)
  async function readHelpers() {
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
    return { helpers: all, unreachable: remote.filter((r) => !r.ok).map((r) => r.id) }
  }
  readHelpers.forget = forgetCache
  return readHelpers
}

export function postDismissTo(host, id, { port = 7878, timeoutMs = REMOTE_TIMEOUT_MS } = {}) {
  return new Promise((resolve) => {
    let answered = false
    const done = (v) => {
      if (!answered) {
        answered = true
        resolve(v)
      }
    }
    const data = JSON.stringify({ id })
    const req = http.request({ host, port, path: '/helpers/dismiss', method: 'POST', timeout: timeoutMs, headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } }, (res) => {
      if (res.statusCode !== 200) {
        res.resume()
        return done({ ok: false })
      }
      let body = ''
      res.setEncoding('utf8')
      res.on('data', (c) => {
        body += c
        if (body.length > 512) {
          done({ ok: false })
          req.destroy()
        }
      })
      res.on('end', () => {
        try {
          done(JSON.parse(body))
        } catch {
          done({ ok: false })
        }
      })
      res.on('close', () => done({ ok: false }))
    })
    req.on('timeout', () => {
      done({ ok: false })
      req.destroy()
    })
    req.on('error', () => done({ ok: false }))
    req.write(data)
    req.end()
  })
}

export function createHelperDismisser({ dismissLocal, postRemote, resolveMe = () => 'local', peers = () => [] } = {}) {
  return async function dismissHelper(id, machineId) {
    const me = resolveMe()
    if (machineId === me || !machineId) {
      return dismissLocal(id)
    }
    const peer = peers().find((p) => p.id === machineId)
    if (!peer) return { ok: false, error: 'peer not found' }
    return postRemote(peer.host, id)
  }
}
