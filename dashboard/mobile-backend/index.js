import { createServer } from 'http'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { homedir } from 'os'
import path from 'path'
import { fileURLToPath } from 'url'
import { whois, loadAllowlist, isAllowed } from './device_gate.js'
import { createDashboardApiRouter } from './dashboard_api.js'
import { createChatApiRouter } from './chat_api.js'
import { createOfflineBatchApiRouter } from './offline_batch_api.js'
import { createThreadStore } from './thread_store.js'
import { createPendingActionsStore } from './pending_actions.js'
import { createPermissionApiRouter } from './permission_api.js'
import { createLiveChannel } from './live_channel.js'
import { createLiveApiRouter } from './live_api.js'
import { createActionsApiRouter } from './actions_api.js'
import { postTicketInput } from '../electron/main/ticket_input.js'
import { approveMr, denyMr } from '../electron/main/mr_review.js'
import { resolveServiceDefaults } from '../electron/main/device_identity.js'

const execFileP = promisify(execFile)

const TAILSCALE_BIN = '/Applications/Tailscale.app/Contents/MacOS/Tailscale'
const PORT = process.env.PORT || 7880
const ALLOWLIST_PATH = path.join(homedir(), '.claude', 'mobile-allowlist.json')

// Resolve webhook URLs the same way Electron does (ADR 0032)
const { host: defaultWebhookHost } = resolveServiceDefaults()
const MR_WEBHOOK_URL = process.env.MARVIN_MR_WEBHOOK_URL || `http://${defaultWebhookHost}:7878/approve`
const MR_DENY_WEBHOOK_URL = process.env.MARVIN_MR_DENY_WEBHOOK_URL || `http://${defaultWebhookHost}:7878/deny`

// POST JSON to a webhook URL
async function postJson(url, payload) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(payload)
    const urlObj = new URL(url)
    const options = {
      hostname: urlObj.hostname,
      port: urlObj.port,
      path: urlObj.pathname + urlObj.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    }

    const http = urlObj.protocol === 'https:' ? require('https') : require('http')
    const req = http.request(options, (res) => {
      let data = ''
      res.on('data', (chunk) => { data += chunk })
      res.on('end', () => {
        try {
          const json = JSON.parse(data)
          resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, json: async () => json })
        } catch {
          resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, json: async () => ({ error: data }) })
        }
      })
    })

    req.on('error', reject)
    req.write(body)
    req.end()
  })
}

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
const offlineBatchApiRouter = createOfflineBatchApiRouter({ threadStore })
const pendingActionStore = createPendingActionsStore()
const permissionApiRouter = createPermissionApiRouter({ pendingActionStore })
const liveChannel = createLiveChannel()
const liveApiRouter = createLiveApiRouter(liveChannel)

// Actions API: confirmed-gated write operations (ticket reply, MR approve/deny)
const actionsApiRouter = createActionsApiRouter({
  postTicketInputFn: postTicketInput,
  approveMrFn: (prUrl, post) => approveMr(prUrl, MR_WEBHOOK_URL, post),
  denyMrFn: (payload, post) => denyMr(payload, MR_DENY_WEBHOOK_URL, post),
  postJson
})

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

  // Route through actions API (ticket reply, MR approve/deny)
  handled = await actionsApiRouter(req, res)
  if (handled) return

  // Route through dashboard API
  handled = await dashboardApiRouter(req, res)
  if (handled) return

  // Route through chat API
  handled = await chatApiRouter(req, res)
  if (handled) return

  // Route through offline batch API
  handled = await offlineBatchApiRouter(req, res)
  if (handled) return

  // Route through live API
  handled = await liveApiRouter(req, res)
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
