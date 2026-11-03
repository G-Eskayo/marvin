import { createServer } from 'http'

// Tiny local server the webhook-server process (a separate process, see
// dashboard/webhook-server/refresh_relay.js) pings whenever a new MR is
// raised or the review list otherwise changes -- this is what actually
// lets an already-open dashboard update immediately instead of relying
// only on its own fallback poll. Kept as its own module (not inlined into
// electron/main/index.js) so the routing itself is testable without a
// real BrowserWindow.
//
// `onShow` (marvin show, G-Eskayo/marvin#715): POST /show with a JSON body asks the dashboard to show Gil one item in
// its project's window; the handler's answer goes back as JSON. Only a local program can ask: the body must be JSON
// (a browser page can't send that cross-site without a preflight, which this server never answers) and a request
// with an Origin or Referer is refused. Bodies are capped at 64 KB.
export const MAX_SHOW_BODY = 64 * 1024

export function createRefreshServer(onRefresh, { onShow = null, showAllowed = defaultShowAllowed } = {}) {
  return createServer((req, res) => {
    if (onShow && req.url === '/show') {
      handleShow(req, res, onShow, showAllowed)
      return
    }
    if (req.method !== 'POST' || req.url !== '/refresh') {
      res.writeHead(404).end()
      return
    }
    let raw = ''
    req.on('data', (chunk) => (raw += chunk))
    req.on('end', () => {
      // Optional body {topics, source} says what changed; empty/invalid = the
      // legacy "MR list changed" ping.
      let payload = {}
      try {
        const parsed = JSON.parse(raw)
        if (parsed && typeof parsed === 'object') payload = parsed
      } catch {
        // no body, or not JSON
      }
      onRefresh(payload)
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: true }))
    })
  })
}

function defaultShowAllowed(headers = {}) {
  const type = String(headers['content-type'] || '').split(';')[0].trim().toLowerCase()
  return type === 'application/json' && headers.origin == null && headers.referer == null
}

function handleShow(req, res, onShow, showAllowed) {
  const reply = (status, body) => {
    if (!res.headersSent) res.writeHead(status, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify(body))
  }
  if (req.method !== 'POST') return reply(405, { ok: false, reason: 'POST only' })
  if (!showAllowed(req.headers)) {
    req.resume()
    return reply(403, { ok: false, reason: 'Only a local program can ask to show something' })
  }
  let raw = ''
  let tooBig = false
  req.on('data', (chunk) => {
    if (tooBig) return
    raw += chunk
    if (raw.length > MAX_SHOW_BODY) {
      tooBig = true
      raw = ''
    }
  })
  req.on('end', async () => {
    if (tooBig) return reply(413, { ok: false, reason: 'Request too large' })
    let body
    try {
      body = JSON.parse(raw)
    } catch {
      return reply(400, { ok: false, reason: 'The body must be JSON' })
    }
    try {
      const out = await onShow(body)
      reply(out?.ok ? 200 : 422, out || { ok: false, reason: 'No answer' })
    } catch (err) {
      reply(500, { ok: false, reason: String(err?.message || err) })
    }
  })
}

export const DEFAULT_REFRESH_PORT = 7879

// MARVIN_DASHBOARD_REFRESH_PORT -> a port number. 0 is honoured (ephemeral: the
// evidence-capture copy uses it so it can never take the real dashboard's port);
// unset, empty or anything that isn't a plain integer in 0-65535 falls back to 7879.
export function parseRefreshPort(raw, fallback = DEFAULT_REFRESH_PORT) {
  const text = typeof raw === 'string' ? raw.trim() : ''
  if (!/^\d{1,5}$/.test(text)) return fallback
  const port = Number(text)
  return port <= 65535 ? port : fallback
}

// Start the refresh server without ever crashing the main process. A second copy
// of the app (the pipeline's evidence capture, or a dev run beside the installed
// app) finds the port taken; without an 'error' listener that EADDRINUSE is an
// uncaught exception and Electron shows a modal error dialog (G-Eskayo/marvin#384).
// Here it's one log line and this instance just doesn't get live refresh pings
// (its fallback poll still runs).
export function startRefreshServer(onRefresh, { port = DEFAULT_REFRESH_PORT, host = '127.0.0.1', log = console.warn, onShow = null } = {}) {
  const server = createRefreshServer(onRefresh, { onShow })
  server.on('error', (err) => {
    const line =
      err?.code === 'EADDRINUSE'
        ? `refresh port ${port} in use — another dashboard is running; live refresh pings disabled for this instance`
        : `refresh server failed to start on ${host}:${port} (${err?.code || err?.message || err}); live refresh pings disabled for this instance`
    try {
      log(line)
    } catch {
      // logging must never be what takes the main process down
    }
  })
  server.listen(port, host)
  return server
}
