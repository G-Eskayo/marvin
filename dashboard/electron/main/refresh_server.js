import { createServer } from 'http'

// Tiny local server the webhook-server process (a separate process, see
// dashboard/webhook-server/refresh_relay.js) pings whenever a new MR is
// raised or the review list otherwise changes -- this is what actually
// lets an already-open dashboard update immediately instead of relying
// only on its own fallback poll. Kept as its own module (not inlined into
// electron/main/index.js) so the routing itself is testable without a
// real BrowserWindow.
export function createRefreshServer(onRefresh) {
  return createServer((req, res) => {
    if (req.method !== 'POST' || req.url !== '/refresh') {
      res.writeHead(404).end()
      return
    }
    onRefresh()
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: true }))
  })
}
