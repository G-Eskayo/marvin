import http from 'http'
import { execFile } from 'child_process'
import { homedir } from 'os'
import path from 'path'

// The live chat tabs on this Mac and the other one (marvin#1064, PRD #1058), for the dashboard's Sessions list and
// for sending. This Mac's come from lib/session_work.py (records joined with WezTerm, #1060/#1061); the other Mac's
// from its webhook server's GET /chats, read-only. Never an empty list that hides work: WezTerm down, a lister
// error and an unreachable Mac are states. The socket and tty stay in the main process.
export const REMOTE_TTL_MS = 10000 // read-through cache bound on the LAN read; no timer of its own
const REMOTE_TIMEOUT_MS = 1500
const LOCAL_TIMEOUT_MS = 8000
const MAX_BYTES = 512 * 1024
const STATES = new Set(['working', 'waiting', 'your-turn', 'done'])
const PY = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const SESSION_WORK = path.join(homedir(), '.agents', 'lib', 'session_work.py')

export function parseLocal(stdout) {
  const line = String(stdout).trim().split('\n').pop()
  const out = JSON.parse(line)
  if (!out || !Array.isArray(out.chats)) throw new Error('session_work gave no chat list')
  return { wezterm: out.wezterm !== false, chats: out.chats }
}

export function listLocalChats({ run = execFile } = {}) {
  return new Promise((resolve, reject) => {
    run(PY, [SESSION_WORK, 'chats', '--json'], { timeout: LOCAL_TIMEOUT_MS, maxBuffer: MAX_BYTES }, (err, stdout) => {
      if (err) return reject(err)
      try {
        resolve(parseLocal(stdout))
      } catch (e) {
        reject(e)
      }
    })
  })
}

export function fetchChatsFrom(host, { port = 7878, timeoutMs = REMOTE_TIMEOUT_MS } = {}) {
  return new Promise((resolve) => {
    let answered = false
    const done = (v) => {
      if (!answered) {
        answered = true
        resolve(v)
      }
    }
    const req = http.get({ host, port, path: '/chats', timeout: timeoutMs }, (res) => {
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
          const got = JSON.parse(body)
          done(got && Array.isArray(got.chats) ? got : null)
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

const str = (v, max) => (typeof v === 'string' ? v.slice(0, max) : null)

// What the renderer may see of one chat. here=false makes it read-only, whatever the row claims.
export function sanitize(c, here) {
  if (!c || typeof c !== 'object' || !Number.isInteger(c.pane) || c.pane < 0) return null
  const unknown = c.unknown === true
  const state = unknown ? 'unknown' : STATES.has(c.state) ? c.state : 'unknown'
  const live = here && !unknown
  return {
    mac: str(c.mac, 60), pane: c.pane, ticket: Number.isInteger(c.ticket) ? c.ticket : null, repo: str(c.repo, 120),
    branch: str(c.branch, 200), cwd: str(c.cwd, 400), title: str(c.title, 120) || '', state,
    waitingFor: c.waiting_for === 'permission' || c.waiting_for === 'question' ? c.waiting_for : null,
    canFocus: live, canSend: live
  }
}

export function createChatsReader({ listLocal = () => listLocalChats(), peers = () => [], fetchRemote = fetchChatsFrom, clock = () => Date.now() } = {}) {
  const cache = new Map()
  return async function readChats() {
    let here
    try {
      const got = await listLocal()
      here = { id: 'this-mac', here: true, status: got.wezterm ? 'ok' : 'wezterm-down',
        chats: got.chats.map((c) => sanitize(c, true)).filter(Boolean) }
    } catch (err) {
      here = { id: 'this-mac', here: true, status: 'error', error: String(err?.message || err).slice(0, 200), chats: [] }
    }
    const others = await Promise.all(peers().map(async ({ id, host }) => {
      const hit = cache.get(id)
      if (hit && clock() - hit.at < REMOTE_TTL_MS) return hit.value
      const got = await fetchRemote(host)
      const value = got === null
        ? { id, here: false, status: 'unreachable', chats: [] }
        : { id, here: false, status: got.wezterm === false ? 'wezterm-down' : 'ok',
            chats: got.chats.map((c) => sanitize(c, false)).filter(Boolean) }
      cache.set(id, { at: clock(), value })
      return value
    }))
    return { macs: [here, ...others] }
  }
}
