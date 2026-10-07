import { requestPermission } from './permission_bridge.js'

export const DEFAULT_INTERNAL_PORT = 3001

export function createInternalApiRouter(opts = {}) {
  const { store, timeoutMs } = opts

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /internal/permission-check
      if (req.method === 'POST' && pathname === '/internal/permission-check') {
        // Read body as JSON
        let body = ''
        for await (const chunk of req) {
          body += chunk.toString()
        }

        let payload
        try {
          payload = JSON.parse(body)
        } catch {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Invalid JSON' })
          )
          return true
        }

        const { toolName, toolInput } = payload
        if (!toolName || typeof toolName !== 'string') {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid toolName field' })
          )
          return true
        }

        // Request permission (may wait for user approval or timeout)
        const result = await requestPermission(toolName, toolInput || {}, { store, timeoutMs })

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify(result)
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
