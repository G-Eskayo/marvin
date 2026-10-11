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
import { parsePrImages, createImageLoader, mediaFileFor } from '../electron/main/pr_images.js'
import { parseTicketRef, needsImages } from '../electron/main/mr_review.js'
import { readUiPaths } from '../electron/main/profiles.js'
import { streamFileWithRange } from './range_stream.js'

const execFileP = promisify(execFile)

// The folder the pipeline writes to (#216: this used to be ~/.claude/ticket-stages, which nothing writes).
export const DEFAULT_STAGES_DIR = STAGES_DIR
const DISPATCH_STATE_PATH = path.join(homedir(), '.claude', '.dispatch-status.json')
export const MR_MEDIA_CACHE_DIR = path.join(homedir(), '.claude', 'mr-media-cache')

export function createDashboardApiRouter(opts = {}) {
  const stagesDir = opts.stagesDir ?? DEFAULT_STAGES_DIR
  const dispatchStatePath = opts.dispatchStatePath ?? DISPATCH_STATE_PATH
  const healthStatusPath = opts.healthStatusPath ?? HEALTH_STATUS_PATH
  const registryPath = opts.registryPath ?? REGISTRY_PATH
  const catalogDir = opts.catalogDir ?? CATALOG_DIR
  const masterDocPath = opts.masterDocPath ?? MASTER_DOC_PATH
  const deviceId = opts.deviceId ?? resolveDeviceId()
  const exec = opts.exec ?? execFileP
  const mrMediaCacheDir = opts.mrMediaCacheDir ?? MR_MEDIA_CACHE_DIR
  const MARVIN_REPO = opts.MARVIN_REPO ?? 'G-Eskayo/marvin'

  const docsService = createDocsService({
    getCatalog: () => readCatalog({ dir: catalogDir, deviceId }),
    exec,
    readMaster: () => readMasterDoc(masterDocPath)
  })

  // Image loader singleton for media caching and de-duplication
  const imageLoader = createImageLoader({
    cacheDir: mrMediaCacheDir,
    mediaUrl: (id) => id
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

      // GET /mr/image?url=<encoded>&kind=<image|video|auto>
      if (req.method === 'GET' && pathname === '/mr/image') {
        const url = searchParams.get('url')
        const kind = searchParams.get('kind') || 'auto'
        if (!url) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing url parameter' })
          )
          return true
        }
        const result = await imageLoader.load(url, kind)
        if (!result.ok) {
          res.writeHead(502, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: result.reason })
          )
          return true
        }
        if (result.kind === 'image') {
          const buffer = Buffer.from(result.dataUrl.split(',')[1], 'base64')
          res.writeHead(200, {
            'Content-Type': result.mime || 'application/octet-stream',
            'Content-Length': buffer.length
          }).end(buffer)
          return true
        }
        if (result.kind === 'video') {
          const video = mediaFileFor(mrMediaCacheDir, result.src)
          if (video) {
            streamFileWithRange(req, res, video.file, video.mime)
          } else {
            res.writeHead(502, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: 'Video file not found' })
            )
          }
          return true
        }
        res.writeHead(502, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: false, error: 'Unknown media kind' })
        )
        return true
      }

      // GET /mr/<owner>/<name>/<number> - PR detail with images
      if (req.method === 'GET' && pathname.startsWith('/mr/')) {
        const parts = pathname.slice(1).split('/').filter(p => p)
        if (parts.length !== 4 || parts[0] !== 'mr') {
          return false
        }
        const [, owner, name, number] = parts
        if (!/^[\w.-]+$/.test(owner) || !/^[\w.-]+$/.test(name) || !/^\d+$/.test(number)) {
          return false
        }
        const repo = `${owner}/${name}`
        const registry = readRegistry(registryPath)
        const isValidRepo = repo === MARVIN_REPO || registry.some(b => b.repo === repo)
        if (!isValidRepo) {
          res.writeHead(403, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Repository not authorized' })
          )
          return true
        }
        const { stdout } = await exec('gh', [
          'pr', 'view', number, '--repo', repo,
          '--json', 'number,title,url,body,headRefName,files'
        ])
        const pr = JSON.parse(stdout)
        const images = parsePrImages(pr.body || '', { repo, headRef: pr.headRefName })
        const ticketRef = parseTicketRef(pr.body || '')
        const checkNeedsImages = needsImages(pr, (r) => readUiPaths(r))
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({
            ok: true,
            data: {
              number: pr.number,
              title: pr.title,
              url: pr.url,
              repo,
              images,
              ticketRef,
              needsImages: checkNeedsImages
            }
          })
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
