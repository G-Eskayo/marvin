export function createPermissionApiRouter(opts = {}) {
  const { store } = opts

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // GET /pending-actions
      if (req.method === 'GET' && pathname === '/pending-actions') {
        const actions = store.list()
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, actions })
        )
        return true
      }

      // POST /pending-actions/:id/approve
      if (req.method === 'POST' && pathname.match(/^\/pending-actions\/[^/]+\/approve$/)) {
        const match = pathname.match(/^\/pending-actions\/([^/]+)\/approve$/)
        const id = match[1]
        const resolved = store.resolve(id, 'approved')
        if (!resolved) {
          res.writeHead(404, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Action not found' })
          )
          return true
        }
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true })
        )
        return true
      }

      // POST /pending-actions/:id/deny
      if (req.method === 'POST' && pathname.match(/^\/pending-actions\/[^/]+\/deny$/)) {
        const match = pathname.match(/^\/pending-actions\/([^/]+)\/deny$/)
        const id = match[1]
        const resolved = store.resolve(id, 'denied')
        if (!resolved) {
          res.writeHead(404, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Action not found' })
          )
          return true
        }
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true })
        )
        return true
      }

      // No route matched
      return false
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ ok: false, error: err.message })
      )
      return true
    }
  }
}
