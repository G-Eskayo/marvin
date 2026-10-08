import { homedir } from 'os'
import path from 'path'
import { promisify } from 'util'
import { execFile } from 'child_process'
import { listTicketActivity } from '../electron/main/activity.js'
import { STAGES_DIR } from '../webhook-server/ticket_stages.js'
import { readHealthStatus, HEALTH_STATUS_PATH } from '../electron/main/health.js'
import { readRegistry, REGISTRY_PATH, withProjectStatus } from '../electron/main/boards.js'
import { readCatalog, CATALOG_DIR, MASTER_DOC_PATH, readMasterDoc } from '../electron/main/catalog.js'
import { resolveDeviceId } from '../electron/main/device_identity.js'
import { createDocsService } from '../electron/main/docs_service.js'
import { postTicketInput } from '../electron/main/ticket_input.js'

const execFileP = promisify(execFile)

// The folder the pipeline writes to (#216: this used to be ~/.claude/ticket-stages, which nothing writes).
export const DEFAULT_STAGES_DIR = STAGES_DIR
const DISPATCH_STATE_PATH = path.join(homedir(), '.claude', '.dispatch-status.json')

export function createDashboardApiRouter(opts = {}) {
  const stagesDir = opts.stagesDir ?? DEFAULT_STAGES_DIR
  const dispatchStatePath = opts.dispatchStatePath ?? DISPATCH_STATE_PATH
  const healthStatusPath = opts.healthStatusPath ?? HEALTH_STATUS_PATH
  const registryPath = opts.registryPath ?? REGISTRY_PATH
  const catalogDir = opts.catalogDir ?? CATALOG_DIR
  const masterDocPath = opts.masterDocPath ?? MASTER_DOC_PATH
  const deviceId = opts.deviceId ?? resolveDeviceId()
  const exec = opts.exec ?? execFileP

  const docsService = createDocsService({
    getCatalog: () => readCatalog({ dir: catalogDir, deviceId }),
    exec,
    readMaster: () => readMasterDoc(masterDocPath)
  })

  // Handler for all dashboard API routes
  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname
    const searchParams = url.searchParams

    try {
      // GET /activity
      if (req.method === 'GET' && pathname === '/activity') {
        const activity = listTicketActivity(dispatchStatePath, stagesDir)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: activity })
        )
        return true
      }

      // GET /health
      if (req.method === 'GET' && pathname === '/health') {
        const health = readHealthStatus(healthStatusPath)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: health })
        )
        return true
      }

      // GET /boards
      if (req.method === 'GET' && pathname === '/boards') {
        const boards = readRegistry(registryPath)
        const catalog = readCatalog({ dir: catalogDir, deviceId })
        const withStatus = withProjectStatus(boards, catalog)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: withStatus })
        )
        return true
      }

      // GET /boards/ticket?repo=<repo>&number=<number>
      if (req.method === 'GET' && pathname === '/boards/ticket') {
        const repo = searchParams.get('repo')
        const number = searchParams.get('number')
        if (!repo || !number) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing repo or number parameter' })
          )
          return true
        }
        const { stdout } = await exec('gh', [
          'issue', 'view', String(Number(number)), '--repo', repo,
          '--json', 'number,title,body,labels,url,state,comments'
        ])
        const data = JSON.parse(stdout)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data })
        )
        return true
      }

      // POST /boards/input
      if (req.method === 'POST' && pathname === '/boards/input') {
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

        const { repo, number, body: commentBody, confirmed } = payload

        if (confirmed !== true) {
          res.writeHead(403, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Action requires Face ID confirmation (confirmed: true)' })
          )
          return true
        }

        if (!repo || !number || !commentBody) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing required fields: repo, number, body' })
          )
          return true
        }

        try {
          const result = await postTicketInput({ repo, number, body: commentBody }, exec)
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: result })
          )
        } catch (err) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: err.message })
          )
        }
        return true
      }

      // GET /docs/repos
      if (req.method === 'GET' && pathname === '/docs/repos') {
        const data = await docsService.repos()
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data })
        )
        return true
      }

      // GET /docs/tree?id=<id>
      if (req.method === 'GET' && pathname === '/docs/tree') {
        const id = searchParams.get('id')
        if (!id) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing id parameter' })
          )
          return true
        }
        const data = await docsService.tree(id)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data })
        )
        return true
      }

      // GET /docs/content?id=<id>&path=<path>
      if (req.method === 'GET' && pathname === '/docs/content') {
        const id = searchParams.get('id')
        const filePath = searchParams.get('path')
        if (!id || !filePath) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing id or path parameter' })
          )
          return true
        }
        const data = await docsService.content(id, filePath)
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data })
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
