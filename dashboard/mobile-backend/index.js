import { createServer } from 'http'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { homedir } from 'os'
import path from 'path'
import { fileURLToPath } from 'url'
import { whois, loadAllowlist, isAllowed } from './device_gate.js'
import { createDashboardApiRouter } from './dashboard_api.js'
import { createChatApiRouter } from './chat_api.js'
import { createThreadStore } from './thread_store.js'
import { createPendingActionsStore } from './pending_actions.js'
import { createPermissionApiRouter } from './permission_api.js'
import { createActionsApiRouter } from './actions_api.js'

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

const dashboardApiRouter = createDashboardApiRouter()
const threadStore = createThreadStore()
const chatApiRouter = createChatApiRouter({ threadStore })
const pendingActionStore = createPendingActionsStore()
const permissionApiRouter = createPermissionApiRouter({ pendingActionStore })
const actionsApiRouter = createActionsApiRouter()

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

  // Route through permission API
  let handled = await permissionApiRouter(req, res)
  if (handled) return

  // Route through actions API (write operations)
  handled = await actionsApiRouter(req, res)
  if (handled) return

  // Route through dashboard API
  handled = await dashboardApiRouter(req, res)
  if (handled) return

  // Route through chat API
  handled = await chatApiRouter(req, res)
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

// Resolve Tailscale IP and start listening
const tailscaleIp = await resolveTailscaleIp()
server.listen(PORT, tailscaleIp, () => {
  console.log(`Mobile backend listening on http://${tailscaleIp}:${PORT}/status`)
})
