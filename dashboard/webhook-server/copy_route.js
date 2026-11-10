// GET /copy/<name> (marvin#1223): this Mac's own stamped copies, for a peer whose own copy has gone stale. Gil's
// decision (2026-11-09): a Mac that isn't producing a file shows the producer's live copy, labelled with its Mac and
// age (lib/stamped.py, electron/main/stamped.js). This is the read half of the Vitals plan's peer push (P2, GET
// /health), narrowed to four files.
//
// Fails closed: only loopback and Tailscale addresses (merge_stage_relay.allowedPeerAddress, the /merge-stage rule);
// only GET; only the four names below (no path is ever built from the request); a body over maxBytes is 413; a file
// that isn't a JSON object is 502 and its text is never echoed. Read-only: nothing here writes.
import { readFileSync, statSync } from 'fs'
import { homedir } from 'os'
import { join } from 'path'
import { allowedPeerAddress } from './merge_stage_relay.js'

export const COPY_NAMES = ['health-status', 'ticket-agent-proposals', 'dispatch-state', 'boards-registry']
const HOME = homedir()
export const COPY_PATHS = {
  'health-status': join(HOME, '.claude', 'logs', 'health-status.json'),
  'ticket-agent-proposals': join(HOME, '.claude', 'logs', 'ticket-agent-proposals.json'),
  'dispatch-state': join(HOME, '.claude', 'dispatch-state.json'),
  'boards-registry': join(HOME, '.claude', 'boards', 'registry.json')
}
const MAX_BYTES = 2 * 1024 * 1024

const send = (res, status, body) => res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }).end(body)

// true when this request was a /copy/ request (answered here, whatever the answer); false to let other routes look.
export function copyRoute(req, res, { paths = COPY_PATHS, maxBytes = MAX_BYTES } = {}) {
  const url = String(req.url || '')
  const pathname = url.split('?')[0]
  if (!pathname.startsWith('/copy/')) return false
  if (!allowedPeerAddress(req.socket?.remoteAddress)) {
    send(res, 403, JSON.stringify({ error: 'forbidden' }))
    return true
  }
  if (req.method !== 'GET') {
    send(res, 405, JSON.stringify({ error: 'GET only' }))
    return true
  }
  const name = pathname.slice('/copy/'.length)
  if (!COPY_NAMES.includes(name) || !Object.prototype.hasOwnProperty.call(paths, name)) {
    send(res, 404, JSON.stringify({ error: 'no such copy' }))
    return true
  }
  let text
  try {
    if (statSync(paths[name]).size > maxBytes) {
      send(res, 413, JSON.stringify({ error: 'too large' }))
      return true
    }
    text = readFileSync(paths[name], 'utf-8')
  } catch {
    send(res, 404, JSON.stringify({ error: 'not here yet' }))
    return true
  }
  let data
  try {
    data = JSON.parse(text)
  } catch {
    data = null
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    send(res, 502, JSON.stringify({ error: 'copy unreadable' }))
    return true
  }
  send(res, 200, JSON.stringify(data))
  return true
}
