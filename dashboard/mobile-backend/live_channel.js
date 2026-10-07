import { homedir } from 'os'
import path from 'path'
import { dirname } from 'path'
import { createTriggerHub } from '../electron/main/triggers.js'

const STAGES_DIR = path.join(homedir(), '.claude', 'ticket-stages')
const DISPATCH_STATE_PATH = path.join(homedir(), '.claude', '.dispatch-status.json')
const REGISTRY_PATH = path.join(homedir(), '.claude', 'registry.json')
const CATALOG_DIR = path.join(homedir(), '.claude', 'catalog')
const MASTER_DOC_PATH = path.join(homedir(), '.claude', 'catalog', 'master.md')

export function createLiveChannel(opts = {}) {
  const stagesDir = opts.stagesDir ?? STAGES_DIR
  const dispatchStatePath = opts.dispatchStatePath ?? DISPATCH_STATE_PATH
  const registryPath = opts.registryPath ?? REGISTRY_PATH
  const catalogDir = opts.catalogDir ?? CATALOG_DIR
  const masterDocPath = opts.masterDocPath ?? MASTER_DOC_PATH
  const createHub = opts.createHub ?? createTriggerHub

  let triggerHub = null
  const connections = new Set()
  let heartbeatInterval = null

  function startHub() {
    if (triggerHub) return

    triggerHub = createHub()

    triggerHub.watchFiles('activity', [
      { dir: stagesDir, match: (n) => n.endsWith('.json') },
      { dir: dirname(dispatchStatePath), match: (n) => n === '.dispatch-status.json' },
      { dir: dirname(registryPath), match: (n) => n === 'registry.json' }
    ])

    triggerHub.watchFiles('docs', [
      { dir: catalogDir, match: (n) => !n.startsWith('.') },
      { dir: dirname(masterDocPath), match: (n) => n === 'master.md' }
    ])

    triggerHub.onTrigger((trigger) => {
      if (['activity', 'docs'].includes(trigger.topic)) {
        broadcast(trigger)
      }
    })

    heartbeatInterval = setInterval(() => {
      for (const res of connections) {
        res.write(': heartbeat\n\n')
      }
    }, 30000)
  }

  function stopHub() {
    if (!triggerHub || connections.size > 0) return

    triggerHub.close()
    triggerHub = null
    if (heartbeatInterval) {
      clearInterval(heartbeatInterval)
      heartbeatInterval = null
    }
  }

  function broadcast(trigger) {
    const data = JSON.stringify({ topic: trigger.topic, source: trigger.source })
    for (const res of connections) {
      res.write(`event: trigger\ndata: ${data}\n\n`)
    }
  }

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    // Only handle GET /live
    if (req.method !== 'GET' || pathname !== '/live') {
      return false
    }

    // Write SSE headers
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive'
    })

    // Send initial connected frame
    res.write('event: connected\ndata: {"ok":true}\n\n')

    // Add to connections and start hub on first client
    connections.add(res)
    if (connections.size === 1) {
      startHub()
    }

    // Clean up on disconnect
    req.on('close', () => {
      connections.delete(res)
      res.destroy()
      if (connections.size === 0) {
        stopHub()
      }
    })

    return true
  }
}
