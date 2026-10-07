import { createServer } from 'http'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { homedir } from 'os'
import path from 'path'
import { whois, loadAllowlist, isAllowed } from './device_gate.js'
import { createDashboardApiRouter } from './dashboard_api.js'
import { createChatApiRouter } from './chat_api.js'
import { createPermissionApiRouter } from './permission_api.js'
import { createInternalApiRouter, DEFAULT_INTERNAL_PORT } from './internal_api.js'
import { createPendingActionStore } from './permission_bridge.js'

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

// Shared permission action store
const permissionStore = createPendingActionStore()

const dashboardApiRouter = createDashboardApiRouter()
const chatApiRouter = createChatApiRouter()
const permissionApiRouter = createPermissionApiRouter({ store: permissionStore })
const internalApiRouter = createInternalApiRouter({ store: permissionStore })

const server = createServer(async (req, res) => {
  // Device gate: check allowlist
  const ip = req.socket.remoteAddress || req.connection.remoteAddress
  const peer = await whois(ip)
  const allowlist = loadAllowlist(ALLOWLIST_PATH)
  const allowed = isAllowed(peer, allowlist)

  if (!allowed) {
    res.writeHead(403, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ ok: false, error: 'not allowlisted' })
    )
    return
  }

  // Route through dashboard API
  let handled = await dashboardApiRouter(req, res)
  if (handled) return

  // Route through chat API
  handled = await chatApiRouter(req, res)
  if (handled) return

  // Route through permission API
  handled = await permissionApiRouter(req, res)
  if (handled) return

  // Single endpoint: GET /status
  if (req.method === 'GET' && req.url === '/status') {
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

  // 404 for unmatched routes
  res.writeHead(404).end()
})

// Internal API server: loopback only, for hook communication
const internalServer = createServer((req, res) => {
  internalApiRouter(req, res)
})

const internalPort = process.env.INTERNAL_API_PORT || DEFAULT_INTERNAL_PORT
internalServer.listen(internalPort, '127.0.0.1', () => {
  console.log(`Internal API listening on http://127.0.0.1:${internalPort}`)
})

// Resolve Tailscale IP and start listening
const tailscaleIp = await resolveTailscaleIp()
server.listen(PORT, tailscaleIp, () => {
  console.log(`Mobile backend listening on http://${tailscaleIp}:${PORT}/status`)
})
