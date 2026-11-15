import http from 'http'
import https from 'https'
import { approveMr, describeApproveFailure } from './mr_review.js'

// Approve, with the merge's progress pushed as it happens (marvin#568). Asks the webhook for its streamed answer
// (webhook-server/merge_progress.js approveResponder): one {type:"progress"} line per stage event, handed to
// onEvent, then one {type:"result"} line, which resolves or throws exactly as approveMr does.
//
// node:http, not fetch: fetch gives up on a response after 5 minutes without headers or body (undici's defaults),
// and a retested merge can take longer than that. Here the only end is the webhook's.
//
// The stream ending with no result means the webhook went away mid-merge (restarted, crashed, the Mac slept):
// resolves { merged: false, interrupted: true } at once, instead of the card reading "Merging…" for 45 minutes.
// An older webhook that answers plain JSON is handled the old way, so the two can be updated in any order.
export const MAX_LINE = 64 * 1024
// marvin#762: how long to wait for a connection before calling the machine unreachable. A powered-off Mac on Tailscale
// never refuses, it just doesn't answer, and the OS would wait about 75 s; the owner was clicking Approve again by then.
export const CONNECT_TIMEOUT_MS = 4000
// marvin#1228: if no output for this long, the stream may be stalled. Probe /inflight to check if the merge is still
// running on the webhook.
export const STALL_MS = 30_000

// Could not reach the webhook (refused, no route, no answer to connect): nothing was sent, so another machine may
// merge it instead. Marked `unreachable`, with the OS's code; an error after the connection is never marked.
function unreachable(err, code = err?.code) {
  return Object.assign(err instanceof Error ? err : new Error(String(err)), { unreachable: true, code })
}

export function approveMrStream(prUrl, webhookUrl, { onEvent = () => {}, request = null, connectTimeoutMs = CONNECT_TIMEOUT_MS, checkInflight = null, onNotice = () => {}, stallMs = STALL_MS } = {}) {
  return new Promise((resolve, reject) => {
    let target
    try { target = new URL(webhookUrl) } catch { reject(new Error(`Not a webhook URL: ${webhookUrl}`)); return }
    const send = request || (target.protocol === 'https:' ? https.request : http.request)
    const body = JSON.stringify({ pr_url: prUrl })
    let answered = false, started = false, connected = false, connectTimer = null, stallTimer = null, lastActivity = Date.now()
    const interrupted = () => done(resolve, { merged: false, interrupted: true, reason: 'The merge was interrupted when the webhook restarted. Approve again.' })
    const done = (fn, v) => { clearTimeout(connectTimer); clearTimeout(stallTimer); if (!answered) { answered = true; fn(v) } }
    const resetStallTimer = () => {
      clearTimeout(stallTimer)
      lastActivity = Date.now()
      if (checkInflight && Number.isFinite(stallMs) && stallMs > 0) {
        stallTimer = setTimeout(async () => {
          if (answered || !started) return
          try {
            const inflightRes = await checkInflight(webhookUrl)
            if (inflightRes?.urls?.includes?.(prUrl)) {
              // Still merging on the webhook, send a keepalive notice to the listener.
              try { onNotice?.('Merge still running on the webhook') } catch { /* a listener's mistake never stops the merge */ }
            }
          } catch { /* could not check, keep waiting */ }
        }, stallMs)
        stallTimer.unref?.()
      }
    }
    const req = send(target, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson', 'Content-Length': Buffer.byteLength(body) } }, (res) => {
      started = true
      const type = String(res.headers['content-type'] || '')
      if (!type.includes('application/x-ndjson')) {
        // An older webhook: one plain JSON answer, read through the same code approveMr uses.
        let raw = ''
        res.setEncoding('utf8')
        res.on('data', (c) => { if (raw.length < 1024 * 1024) raw += c })
        res.on('end', () => {
          const response = { ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, json: async () => JSON.parse(raw) }
          approveMr(prUrl, webhookUrl, async () => response).then((v) => done(resolve, v), (e) => done(reject, e))
        })
        res.on('error', (e) => done(reject, e))
        return
      }
      let buf = ''
      const line = (text) => {
        if (!text.trim()) return
        let msg
        try { msg = JSON.parse(text) } catch { return } // a garbled line is skipped, never fatal
        if (msg?.type === 'keepalive') {
          resetStallTimer()
        } else if (msg?.type === 'progress' && msg.event && typeof msg.event === 'object') {
          resetStallTimer()
          try { onEvent(msg.event) } catch { /* a listener's mistake never stops the merge's answer */ }
        } else if (msg?.type === 'result') {
          const status = Number(msg.status)
          if (status >= 200 && status < 300) done(resolve, msg.body)
          else {
            const error = new Error(describeApproveFailure(status, msg.body))
            if (msg.body && msg.body.code) error.payload = msg.body
            done(reject, error)
          }
        }
      }
      res.setEncoding('utf8')
      res.on('data', (chunk) => {
        buf += chunk
        let i
        while ((i = buf.indexOf('\n')) >= 0) { line(buf.slice(0, i)); buf = buf.slice(i + 1) }
        if (buf.length > MAX_LINE) buf = '' // one absurd line cannot grow without bound
      })
      const ended = () => {
        if (buf) { line(buf); buf = '' }
        interrupted()
      }
      const reconcile = async () => {
        if (answered || !started) return
        try {
          const inflightRes = await checkInflight(webhookUrl)
          if (inflightRes?.urls?.includes?.(prUrl)) {
            // Still merging on the webhook: keep waiting for the real result.
            return { merged: false, stillRunning: true, reason: 'Lost contact with the merge, but it is still running. Reconnected.' }
          }
        } catch { /* could not check, keep waiting */ }
        // Either not in /inflight or could not check: end the stream.
        return null
      }
      const endStream = async () => {
        if (buf) { line(buf); buf = '' }
        if (!checkInflight) {
          interrupted()
        } else {
          const result = await reconcile()
          done(resolve, result || { merged: false, interrupted: true, reason: 'The merge was interrupted when the webhook restarted. Approve again.' })
        }
      }
      res.on('end', endStream)
      res.on('aborted', endStream)
      res.on('close', endStream)
      res.on('error', endStream)
      resetStallTimer()
    })
    // Could not reach the webhook at all: nothing started, so this is an error, not an interruption. Once the answer
    // had started, a dropped connection is the webhook going away mid-merge.
    // marvin#762: an error before the socket connected means the request never left; that one is `unreachable`.
    req.on('socket', (socket) => {
      if (socket && socket.connecting === false) connected = true // a reused keep-alive socket is already connected
      else socket?.once?.('connect', () => { connected = true; clearTimeout(connectTimer) })
    })
    req.on('error', (e) => (started ? interrupted() : done(reject, connected ? e : unreachable(e))))
    if (Number.isFinite(connectTimeoutMs) && connectTimeoutMs > 0) {
      connectTimer = setTimeout(() => {
        if (connected || started) return
        const e = unreachable(new Error(`No answer from ${target.host} within ${Math.round(connectTimeoutMs / 1000)} s`), 'ETIMEDOUT')
        done(reject, e)
        try { req.destroy(e) } catch { /* already gone */ }
      }, connectTimeoutMs)
      connectTimer.unref?.()
    }
    req.end(body)
  })
}
