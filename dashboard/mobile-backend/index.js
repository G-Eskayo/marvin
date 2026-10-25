import { createServer } from 'http'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { homedir } from 'os'
import path from 'path'
import { whois, loadAllowlist, isAllowed } from './device_gate.js'
import { createDashboardApiRouter } from './dashboard_api.js'
import { createChatApiRouter } from './chat_api.js'
import { createThreadStore } from './thread_store.js'
import { createPermissionBridge } from './permission_bridge.js'
import { createPermissionApiRouter } from './permission_api.js'

const execFileP = promisify(execFile)

const TAILSCALE_BIN = '/Applications/Tailscale.app/Contents/MacOS/Tailscale'
const PORT = process.env.PORT || 7880
const PERMISSION_RELAY_PORT = process.env.PERMISSION_RELAY_PORT || 7881
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
const permissionBridge = createPermissionBridge()
const permissionApiRouter = createPermissionApiRouter(permissionBridge)
const chatApiRouter = createChatApiRouter({ threadStore, permissionBridge })

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

  // Route through permission API
  handled = await permissionApiRouter(req, res)
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

// Loopback-only relay server for permission bridge.
// The PreToolUse hook subprocess contacts this to request tool permission.
const relayServer = createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`)
  const pathname = url.pathname

  try {
    if (req.method === 'POST' && pathname === '/permission-relay') {
      let body = ''
      for await (const chunk of req) {
        body += chunk.toString()
      }

      const { tool_name: toolName, tool_input: toolInput } = JSON.parse(body)
      const { id, behavior, promise } = permissionBridge.requestPermission(toolName, toolInput)

      if (behavior === 'allow') {
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ decision: true, reason: 'auto-allow' })
        )
      } else {
        // Pending: wait for the promise to settle, then respond
        const decision = await promise
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ decision, reason: decision ? 'approved' : 'denied/timeout' })
        )
      }
    } else {
      res.writeHead(404).end()
    }
  } catch (err) {
    res.writeHead(500, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ decision: false, reason: `error: ${err.message}` })
    )
  }
})

// Resolve Tailscale IP and start listening
const tailscaleIp = await resolveTailscaleIp()
server.listen(PORT, tailscaleIp, () => {
  console.log(`Mobile backend listening on http://${tailscaleIp}:${PORT}/status`)
})

relayServer.listen(PERMISSION_RELAY_PORT, '127.0.0.1', () => {
  console.log(`Permission relay listening on http://127.0.0.1:${PERMISSION_RELAY_PORT}/`)
})
