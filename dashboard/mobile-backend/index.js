import { createServer } from 'http'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { homedir } from 'os'
import path from 'path'
import { whois, loadAllowlist, isAllowed } from './device_gate.js'
import { createDashboardApi } from './dashboard_api.js'

const execFileP = promisify(execFile)

const TAILSCALE_BIN = '/Applications/Tailscale.app/Contents/MacOS/Tailscale'
const PORT = process.env.PORT || 7880
const ALLOWLIST_PATH = path.join(homedir(), '.claude', 'mobile-allowlist.json')

// Resolve this machine's Tailscale IPv4 address. Fails loud and exits non-zero if unresolvable.
async function resolveTailscaleIp() {
  try {
    const { stdout } = await execFileP(TAILSCALE_BIN, ['ip', '-4'])
    const ip = stdout.trim()
    if (!ip) {
      console.error('ERROR: tailscale ip -4 returned empty')
      process.exit(1)
    }
    console.log(`Resolved Tailscale IPv4: ${ip}`)
    return ip
  } catch (err) {
    console.error(`ERROR: Failed to resolve Tailscale IPv4: ${err.message}`)
    process.exit(1)
  }
}

// Uptime in seconds since this process started.
const startTime = Date.now()
function getUptimeSeconds() {
  return Math.floor((Date.now() - startTime) / 1000)
}

export function createRequestHandler({ dashboardApi, allowlistPath, whoisFn, loadAllowlistFn }) {
  return async (req, res) => {
    // Device gate: check allowlist for all endpoints
    const ip = req.socket.remoteAddress || req.connection.remoteAddress
    const peer = await whoisFn(ip)
    const allowlist = loadAllowlistFn(allowlistPath)
    const allowed = isAllowed(peer, allowlist)

    if (!allowed) {
      res.writeHead(403, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ ok: false, error: 'not allowlisted' })
      )
      return
    }

    // Route dispatch
    const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`)
    const pathname = url.pathname
    const query = Object.fromEntries(url.searchParams)

    try {
      // /status
      if (req.method === 'GET' && pathname === '/status') {
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({
            ok: true,
            status: 'up',
            uptimeSeconds: getUptimeSeconds(),
            version: '1.0.0'
          })
        )
        return
      }

      // /activity
      if (req.method === 'GET' && pathname === '/activity') {
        const result = await dashboardApi.activityList()
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(result))
        return
      }

      // /activity/timeline
      if (req.method === 'GET' && pathname === '/activity/timeline') {
        const number = Number(query.number)
        const repo = query.repo || null
        if (!number || !Number.isInteger(number)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: 'number parameter required' }))
          return
        }
        const result = await dashboardApi.activityTimeline(number, repo)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(result))
        return
      }

      // /health
      if (req.method === 'GET' && pathname === '/health') {
        const result = await dashboardApi.healthStatus()
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(result))
        return
      }

      // /boards
      if (req.method === 'GET' && pathname === '/boards') {
        const result = await dashboardApi.boardsList()
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(result))
        return
      }

      // /boards/ticket
      if (req.method === 'GET' && pathname === '/boards/ticket') {
        const repo = query.repo
        const number = Number(query.number)
        if (!repo || !number || !Number.isInteger(number)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: 'repo and number parameters required' }))
          return
        }
        const result = await dashboardApi.boardsTicket(repo, number)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(result))
        return
      }

      // /docs/repos
      if (req.method === 'GET' && pathname === '/docs/repos') {
        const result = await dashboardApi.docsRepos()
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(result))
        return
      }

      // /docs/tree
      if (req.method === 'GET' && pathname === '/docs/tree') {
        const id = query.id
        if (!id) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: 'id parameter required' }))
          return
        }
        const result = await dashboardApi.docsTree(id)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(result))
        return
      }

      // /docs/content
      if (req.method === 'GET' && pathname === '/docs/content') {
        const id = query.id
        const filePath = query.path
        if (!id || !filePath) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: 'id and path parameters required' }))
          return
        }
        const result = await dashboardApi.docsContent(id, filePath)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(result)
        return
      }

      // 404 for unknown paths
      res.writeHead(404, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: 'not found' }))
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ ok: false, error: err.message })
      )
    }
  }
}

// Bootstrap: resolve IP, create API, start server
const tailscaleIp = await resolveTailscaleIp()
const dashboardApi = createDashboardApi({ exec: execFileP })
const requestHandler = createRequestHandler({
  dashboardApi,
  allowlistPath: ALLOWLIST_PATH,
  whoisFn: whois,
  loadAllowlistFn: loadAllowlist
})

const server = createServer(requestHandler)
server.listen(PORT, tailscaleIp, () => {
  console.log(`Mobile backend listening on http://${tailscaleIp}:${PORT}`)
})
