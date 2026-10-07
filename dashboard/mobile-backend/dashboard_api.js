// Factory for creating a dashboard API that mirrors the in-process Electron handlers.
// All dependencies are passed explicitly — no Electron imports, verified safe for Node-only contexts.
import { listAllTrackedTickets, readStages, STAGES_DIR } from '../webhook-server/ticket_stages.js'
import { readDispatchStatus, DISPATCH_STATE_PATH } from '../electron/main/dispatch_status.js'
import { readHealthStatus, HEALTH_STATUS_PATH } from '../electron/main/health.js'
import { readRegistry, fetchTicket } from '../electron/main/boards.js'
import { CATALOG_DIR, readCatalog, readMasterDoc } from '../electron/main/catalog.js'
import { resolveDeviceId } from '../electron/main/device_identity.js'
import { createDocsService, MASTER_ID } from '../electron/main/docs_service.js'
import { readCachedRepos } from '../electron/main/docs.js'

function summarize(events) {
  if (events.length === 0) return { currentStage: null, currentStatus: null, costUsd: 0, failed: false, title: null }
  const last = events[events.length - 1]
  const costUsd = events.reduce((sum, e) => sum + (e.cost_usd || 0), 0)
  const failed = events.some((e) => e.status === 'failed')
  const title = events.find((e) => e.title)?.title || null
  return { currentStage: last.stage, currentStatus: last.status, costUsd, failed, title }
}

const MARVIN_REPO = 'G-Eskayo/marvin'
function taskIsTicket(task, repo, number) {
  if (!task) return false
  const n = String(number)
  const form = repo === MARVIN_REPO ? `ticket #${n}` : `${repo}#${n}`
  const at = task.indexOf(form)
  if (at < 0) return false
  return !/\d/.test(task.charAt(at + form.length))
}

// Activity helpers — copied from activity.js to avoid circular imports
function listTicketActivityLocal(statePath = DISPATCH_STATE_PATH, stagesDir = STAGES_DIR) {
  const tickets = listAllTrackedTickets(stagesDir)
  const liveDispatch = readDispatchStatus(statePath)
  return tickets.map(({ repo, number }) => {
    const events = readStages(number, stagesDir, repo)
    const summary = summarize(events)
    return {
      repo,
      number,
      key: `${repo}#${number}`,
      ...summary,
      eventCount: events.length,
      lastEventAt: events.length ? events[events.length - 1].timestamp : null,
      isLiveNow: !!(liveDispatch.busy && taskIsTicket(liveDispatch.task, repo, number))
    }
  }).sort((a, b) => {
    if (a.isLiveNow !== b.isLiveNow) return a.isLiveNow ? -1 : 1
    return (b.lastEventAt || '').localeCompare(a.lastEventAt || '')
  })
}

// Boards helper for withProjectStatus
function withProjectStatusLocal(boards, catalog) {
  const projectIdOf = (repo) => repo.split('/')[1].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  const status = Object.fromEntries((catalog?.projects || []).map((p) => [p.id, p.status]))
  return boards.map((b) => ({ ...b, status: status[projectIdOf(b.repo)] || 'recent' }))
}

export function createDashboardApi({ exec, deviceIdOverride = null, catalogDirOverride = null } = {}) {
  const deviceId = deviceIdOverride || resolveDeviceId()
  const catalogDir = catalogDirOverride || CATALOG_DIR

  const ghJson = async (args) => (await exec('gh', args)).stdout
  const assertRegistered = (repo) => {
    if (!readRegistry().some((b) => b.repo === repo)) {
      throw new Error(`No board registered for ${repo}`)
    }
  }

  const docsService = createDocsService({
    getCatalog: () => readCatalog({ dir: catalogDir, deviceId }),
    exec,
    readMaster: () => readMasterDoc(),
    fallbackRepos: () => readCachedRepos().repos
  })

  return {
    // Activity
    async activityList() {
      return listTicketActivityLocal(DISPATCH_STATE_PATH, STAGES_DIR)
    },
    async activityTimeline(number, repo = null) {
      return readStages(number, STAGES_DIR, repo)
    },

    // Health
    async healthStatus() {
      return readHealthStatus(HEALTH_STATUS_PATH)
    },

    // Boards
    async boardsList() {
      const catalog = readCatalog({ dir: catalogDir, deviceId })
      return withProjectStatusLocal(readRegistry(), catalog)
    },
    async boardsTicket(repo, number) {
      assertRegistered(repo)
      return fetchTicket(repo, number, ghJson)
    },

    // Docs
    async docsRepos() {
      return docsService.repos()
    },
    async docsTree(id) {
      return docsService.tree(id)
    },
    async docsContent(id, filePath) {
      return docsService.content(id, filePath)
    }
  }
}
