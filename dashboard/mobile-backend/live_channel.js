import { createTriggerHub } from '../electron/main/triggers.js'
import { createRefreshServer } from '../electron/main/refresh_server.js'
import path from 'path'
import { homedir } from 'os'

const STAGES_DIR = path.join(homedir(), '.claude', 'marvin-dispatch', 'stages')
const DISPATCH_STATE_DIR = path.join(homedir(), '.claude', 'marvin-dispatch', 'state')
const REGISTRY_PATH = path.join(homedir(), '.claude', 'marvin-registry.json')
const JOBS_DIR = path.join(homedir(), '.claude', 'marvin-dispatch', 'jobs')

export function createLiveChannel({
  createTriggerHub: createHub = createTriggerHub,
  createRefreshServer: createServer = createRefreshServer,
  mobRefreshPort = parseInt(process.env.MARVIN_MOBILE_REFRESH_PORT || '7881')
} = {}) {
  let refCount = 0
  let triggerHub = null
  let refreshServer = null
  let listeners = new Set()
  let hubUnsubscribe = null

  function onTrigger(event) {
    listeners.forEach((cb) => cb(event))
  }

  function onRefresh(payload) {
    // Forward refresh pings as trigger events with 'ping' source
    onTrigger({ topic: 'activity', source: 'ping' })
  }

  return {
    connect(listener) {
      listeners.add(listener)
      refCount++

      if (refCount === 1) {
        triggerHub = createHub()
        refreshServer = createServer(onRefresh)

        // Watch activity-related files: stages, dispatch state, registry
        triggerHub.watchFiles('activity', [
          { dir: STAGES_DIR, match: () => true },
          { dir: DISPATCH_STATE_DIR, match: () => true },
          { dir: path.dirname(REGISTRY_PATH), match: (n) => n === path.basename(REGISTRY_PATH) }
        ])

        // Watch agent jobs
        triggerHub.watchFiles('agents', [{ dir: JOBS_DIR, match: () => true }])

        // Listen for trigger events from the hub and relay to all listeners
        hubUnsubscribe = triggerHub.onTrigger(onTrigger)

        // Start the refresh server on loopback
        refreshServer.listen(mobRefreshPort, '127.0.0.1', () => {
          // eslint-disable-next-line no-console
          console.log(`Live channel refresh listener on 127.0.0.1:${mobRefreshPort}`)
        })
      }
    },

    disconnect() {
      refCount--

      if (refCount === 0) {
        if (hubUnsubscribe) hubUnsubscribe()
        if (triggerHub) triggerHub.close()
        if (refreshServer) refreshServer.close()

        triggerHub = null
        refreshServer = null
        hubUnsubscribe = null
        listeners.clear()
      }
    }
  }
}
