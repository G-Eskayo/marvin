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
    id: typeof c.id === 'string' && /^[0-9a-f]{16}$/.test(c.id) ? c.id : null,
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

// Sending into a chat (marvin#1067): only the main dashboard window may ask, only for a chat on this Mac the list
// says can take it, and lib/chat_send.py re-checks everything (idle by its hooks and its title, no prompt on screen)
// at the moment it types. The text goes over stdin, never a command line.
const CHAT_SEND = path.join(homedir(), '.agents', 'lib', 'chat_send.py')

export function createChatSender({ isMainWindow, readChats, run = execFile } = {}) {
  return async function sendToChat(sender, request) {
    if (!isMainWindow(sender)) return { ok: false, why: 'only the main dashboard window can send to a chat' }
    const id = request && typeof request.id === 'string' ? request.id : null
    const text = request && typeof request.text === 'string' ? request.text : null
    if (!id || text === null) return { ok: false, why: 'a send needs a chat id and text' }
    const { macs } = await readChats()
    const chat = macs.filter((m) => m.here).flatMap((m) => m.chats).find((c) => c.id === id)
    if (!chat) return { ok: false, why: 'that chat isn\'t open on this Mac' }
    if (!chat.canSend) return { ok: false, why: 'that chat can\'t take a message right now' }
    return new Promise((resolve) => {
      const child = run(PY, [CHAT_SEND, 'send'], { timeout: 15000, maxBuffer: MAX_BYTES }, (err, stdout) => {
        try {
          resolve(JSON.parse(String(stdout).trim().split('\n').pop()))
        } catch {
          resolve({ ok: false, why: String(err?.message || 'the sender gave no answer').slice(0, 200) })
        }
      })
      child?.stdin?.end(JSON.stringify({ id, text }))
    })
  }
}
