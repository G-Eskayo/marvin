import { createServer } from 'http'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { homedir } from 'os'
import path from 'path'
import { whois, loadAllowlist, isAllowed } from './device_gate.js'
import { resolveClaudeBin } from './claude_bin.js'
import { runSession } from './session_runner.js'
import { createChatHandler } from './chat.js'

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

// Resolve claude binary. Fails loud and exits non-zero if not found.
function resolveClaudeBinOrExit() {
  try {
    const bin = resolveClaudeBin()
    console.log(`Resolved claude binary: ${bin}`)
    return bin
  } catch (err) {
    console.error(`ERROR: ${err.message}`)
    process.exit(1)
  }
}

// Uptime in seconds since this process started.
const startTime = Date.now()
function getUptimeSeconds() {
  return Math.floor((Date.now() - startTime) / 1000)
}

// Device gate check: extract IP, resolve peer, check allowlist.
async function checkDeviceGate(req) {
  const ip = req.socket.remoteAddress || req.connection.remoteAddress
  const peer = await whois(ip)
  const allowlist = loadAllowlist(ALLOWLIST_PATH)
  return isAllowed(peer, allowlist)
}

const claudeBin = resolveClaudeBinOrExit()

// Inject the resolved binary and runSession into the chat handler.
const handleChat = createChatHandler((opts) => runSession({ ...opts, claudeBin }))

const server = createServer(async (req, res) => {
  // Check device gate first for all requests.
  const allowed = await checkDeviceGate(req)
  if (!allowed) {
    res.writeHead(403, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ ok: false, error: 'not allowlisted' })
    )
    return
  }

  // Route to endpoints.
  if (req.method === 'GET' && req.url === '/status') {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({
        ok: true,
        status: 'up',
        uptimeSeconds: getUptimeSeconds(),
        version: '1.0.0'
      })
    )
  } else if (req.method === 'POST' && req.url === '/chat') {
    await handleChat(req, res)
  } else {
    res.writeHead(404).end()
  }
})

// Resolve Tailscale IP and start listening
const tailscaleIp = await resolveTailscaleIp()
server.listen(PORT, tailscaleIp, () => {
  console.log(`Mobile backend listening on http://${tailscaleIp}:${PORT}`)
})
