import { homedir } from 'os'
import path from 'path'
import { promisify } from 'util'
import { execFile } from 'child_process'
import { createReadStream, promises as fs } from 'fs'
import { createGithubState } from '../electron/main/github_state.js'
import { loadBoard, fetchBoardData, getEvidence, readRegistry, REGISTRY_PATH } from '../electron/main/boards.js'
import { listOpenPrsAcrossRepos, prListArgs, canMergeFromDashboard, MARVIN_REPO, normalizeSeen } from '../electron/main/mr_repos.js'
import { listPipelinePrs, sentBackKeys, fetchTicketContext, needsImages } from '../electron/main/mr_review.js'
import { readMergeableRepos, readUiPaths, PROFILES_DIR } from '../electron/main/profiles.js'
import { computeReviewStatus, readSeenNumbers } from '../electron/main/mr_seen.js'
import { getReworkStatus } from '../electron/main/rework.js'
import { getQueue } from '../electron/main/queue.js'
import { getTicketTimeline } from '../electron/main/activity.js'
import { createRelationsService } from '../electron/main/relations_service.js'
import { loadIndex } from '../electron/main/docs_search.js'
import { parsePrImages, createImageLoader, parseRange, mediaFileFor } from '../electron/main/pr_images.js'

const execFileP = promisify(execFile)

const MOBILE_SEEN_PATH = path.join(homedir(), '.claude', 'mobile-mr-seen.json')

export function createDashboardGhApiRouter(opts = {}) {
  const registryPath = opts.registryPath ?? REGISTRY_PATH
  const mergeableProfilesDir = opts.mergeableProfilesDir ?? PROFILES_DIR
  const mobileSeenPath = opts.mobileSeenPath ?? MOBILE_SEEN_PATH
  const mrWebhookUrl = opts.mrWebhookUrl
  const exec = opts.exec ?? execFileP
  const stagesDir = opts.stagesDir ?? path.join(homedir(), '.agents', 'ticket-stages')
  const catalogDir = opts.catalogDir ?? path.join(homedir(), '.agents', 'config', 'catalog.json')
  const masterDocPath = opts.masterDocPath ?? path.join(homedir(), '.agents', 'config', 'docs', 'MASTER.md')
  const reworkRun = opts.rework?.run
  const queueRun = opts.queue?.run
  const mediaCacheDir = opts.mediaCacheDir ?? path.join(homedir(), 'Library', 'Application Support', 'MARVIN Metrics', 'pr-image-cache')
  const mediaLoader = opts.mediaLoader ?? createImageLoader({ cacheDir: mediaCacheDir, token: () => process.env.GH_TOKEN || '' })

  // Module-level singleton for GitHub state (one copy per process)
  const githubState = createGithubState()

  // Helper to get board data (fetched data or cached)
  const getBoardData = async (repo, gh) => {
    return githubState.get('board', repo, () => fetchBoardData(repo, gh))
  }

  // Read registry and convert to array format
  const readRegistryData = () => {
    const registry = readRegistry(registryPath)
    return Array.isArray(registry) ? registry : []
  }

  // Helper to execute GitHub CLI commands and return stdout
  const gh = async (args) => {
    const { stdout } = await exec('gh', args)
    return stdout
  }

  // Helper to get board data for a specific repo (used by relations service)
  const getRepoData = async (repo) => {
    try {
      return await getBoardData(repo, gh)
    } catch {
      return { issues: [], prs: [] }
    }
  }

  // Get all registered repos
  const getRepos = () => readRegistryData().map(b => b.repo)

  // Get docs locally and from index
  const getDocs = async () => {
    try {
      const index = await loadIndex()
      return index.docs || []
    } catch {
      return []
    }
  }

  // Get projects from registry
  const getProjects = () => readRegistryData().map(b => ({
    id: b.repo.split('/')[1].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''),
    repo: b.repo,
    name: b.name
  }))

  // Create relations service for activity/relations routes
  const relations = createRelationsService({
    getRepos,
    getBoardData: getRepoData,
    getDocs,
    getProjects,
    recheck: () => {} // no-op for mobile backend
  })

  // Handler for all dashboard GitHub API routes
  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname
    const searchParams = url.searchParams

    try {
      // GET /boards/load?repo=<repo>
      if (req.method === 'GET' && pathname === '/boards/load') {
        const repo = searchParams.get('repo')
        if (!repo) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing repo parameter' })
          )
          return true
        }

        const registry = readRegistryData()
        const registryRepos = registry.filter(b => b.repo !== repo)
        if (!registry.some(b => b.repo === repo)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: `No board registered for ${repo}` })
          )
          return true
        }

        const data = await getBoardData(repo, gh)
        const evidence = await getEvidence(repo)
        const board = await loadBoard(repo, {
          gh,
          registryRepos,
          data,
          evidence
        })

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: board })
        )
        return true
      }

      // GET /mr/list - List open PRs with merged status and review data
      if (req.method === 'GET' && pathname === '/mr/list') {
        const registry = readRegistryData()
        const repoList = registry.map(b => b.repo)

        // Get open PRs across all repos
        const listOpenPrs = async () => {
          const ghList = async (repo) => {
            const json = await githubState.get('prs', repo, () => gh(prListArgs(repo)))
            return JSON.parse(json)
          }
          const { prs } = await listOpenPrsAcrossRepos(repoList, ghList)
          return prs
        }

        // Helper to get sent back tickets for a set of repos
        const sentBackTickets = async (repos) => {
          const allKeys = new Set()
          for (const repo of repos) {
            try {
              const data = await getBoardData(repo, gh)
              const keys = sentBackKeys(repo, data.issues)
              for (const key of keys) allKeys.add(key)
            } catch {
              // one repo's failure doesn't hide others
            }
          }
          return allKeys
        }

        // Helper to get closed tickets for a set of repos
        const closedTickets = async (repos) => {
          const allKeys = new Set()
          for (const repo of repos) {
            try {
              const data = await getBoardData(repo, gh)
              for (const issue of data.issues || []) {
                if (issue && issue.state === 'CLOSED') {
                  allKeys.add(`${repo}#${issue.number}`)
                }
              }
            } catch {
              // one repo's failure doesn't hide others
            }
          }
          return allKeys
        }

        // Rebase status fetch
        const rebaseStatus = async () => {
          if (!mrWebhookUrl) return {}
          try {
            const url = mrWebhookUrl.replace(/\/approve$/, '/rebase-status')
            const response = await fetch(url, { timeout: 3000 })
            if (!response.ok) return {}
            return await response.json()
          } catch {
            return {}
          }
        }

        // Auto-merge shadow fetch
        const autoMergeShadow = async () => {
          if (!mrWebhookUrl) return {}
          try {
            const url = mrWebhookUrl.replace(/\/approve$/, '/auto-merge-shadow')
            const response = await fetch(url, { timeout: 3000 })
            if (!response.ok) return {}
            return await response.json()
          } catch {
            return {}
          }
        }

        // Get rework status
        const reworkStatus = reworkRun ? async () => getReworkStatus({ run: reworkRun }) : null

        const prs = await listPipelinePrs(listOpenPrs, {
          canMerge: (repo) => canMergeFromDashboard(repo, readMergeableRepos(mergeableProfilesDir)),
          sentBackTickets,
          closedTickets,
          reworkStatus,
          rebaseStatus,
          autoMergeShadow
        })

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: prs })
        )
        return true
      }

      // GET /mr/review-status - Get review status (green/red/blue)
      if (req.method === 'GET' && pathname === '/mr/review-status') {
        const registry = readRegistryData()
        const repoList = registry.map(b => b.repo)

        const listOpenPrs = async () => {
          const ghList = async (repo) => {
            const json = await githubState.get('prs', repo, () => gh(prListArgs(repo, { light: true })))
            return JSON.parse(json)
          }
          const { prs } = await listOpenPrsAcrossRepos(repoList, ghList)
          return prs
        }

        const prs = await listOpenPrs()
        const seenNumbers = normalizeSeen(readSeenNumbers(mobileSeenPath))
        const openCount = prs.length
        // Convert to keys in the format expected by computeReviewStatus
        const prKeys = prs.map(p => `${p.repo || MARVIN_REPO}#${p.number}`)
        const status = computeReviewStatus(prKeys, seenNumbers)

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: { status, openCount } })
        )
        return true
      }

      // GET /mr/ticket-context?ref=<ref>&repo=<repo>
      if (req.method === 'GET' && pathname === '/mr/ticket-context') {
        const ref = searchParams.get('ref')
        const repo = searchParams.get('repo') || MARVIN_REPO

        if (!ref) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing ref parameter' })
          )
          return true
        }

        const registry = readRegistryData()
        if (repo !== MARVIN_REPO && !registry.some(b => b.repo === repo)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: `Repo ${repo} not registered` })
          )
          return true
        }

        const ghIssueView = async (number) => {
          const { stdout } = await exec('gh', [
            'issue', 'view', String(number), '--repo', repo,
            '--json', 'number,title,body'
          ])
          return JSON.parse(stdout)
        }

        const context = await fetchTicketContext(ref, ghIssueView)

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: context })
        )
        return true
      }

      // GET /activity/overview - Activity overview across all projects
      if (req.method === 'GET' && pathname === '/activity/overview') {
        const overview = await relations.overview()
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: overview })
        )
        return true
      }

      // GET /relations/ticket?repo=<repo>&number=<number>
      if (req.method === 'GET' && pathname === '/relations/ticket') {
        const repo = searchParams.get('repo')
        const number = searchParams.get('number')

        if (!repo || !number) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing repo or number parameter' })
          )
          return true
        }

        const numValue = Number(number)
        if (isNaN(numValue)) {
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: { state: 'UNKNOWN', title: '(not loaded)', tickets: [], prs: [] } })
          )
          return true
        }

        const relation = await relations.forTicket(repo, numValue)

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: relation })
        )
        return true
      }

      // GET /relations/context?project=<project>
      if (req.method === 'GET' && pathname === '/relations/context') {
        const project = searchParams.get('project')

        if (!project) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing project parameter' })
          )
          return true
        }

        const context = await relations.context(project)

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data: context })
        )
        return true
      }

      // GET /queue - Get dispatch queue status
      if (req.method === 'GET' && pathname === '/queue') {
        let data = { queue: [], running: [], error: null }
        try {
          if (queueRun) {
            data = await getQueue({ run: queueRun })
          } else {
            data = await getQueue()
          }
        } catch (err) {
          data = { queue: [], running: [], error: String(err.message) }
        }

        res.writeHead(200, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ ok: true, data })
        )
        return true
      }

      // GET /mr/detail?repo=<repo>&number=<number> - Fetch PR detail with images and needsImages flag
      if (req.method === 'GET' && pathname === '/mr/detail') {
        const repo = searchParams.get('repo')
        const number = searchParams.get('number')

        // Validate params
        if (!repo) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing repo parameter' })
          )
          return true
        }
        if (!number || !/^\d+$/.test(number)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid number parameter' })
          )
          return true
        }

        const registry = readRegistryData()
        if (repo !== MARVIN_REPO && !registry.some(b => b.repo === repo)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: `Repo ${repo} not registered` })
          )
          return true
        }

        try {
          const json = await gh(['pr', 'view', number, '--repo', repo, '--json', 'number,title,url,body,headRefName,files'])
          const pr = JSON.parse(json)

          // Compute images and needsImages
          const images = parsePrImages(pr.body || '', { repo, headRef: pr.headRefName })
          const prWithRepo = { ...pr, repo, files: pr.files || [] }
          const needsImagesResult = needsImages(prWithRepo, (r) => readUiPaths(r, mergeableProfilesDir))

          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({
              ok: true,
              data: {
                number: pr.number,
                title: pr.title,
                url: pr.url,
                repo,
                headRef: pr.headRefName,
                needsImages: needsImagesResult,
                images
              }
            })
          )
          return true
        } catch (err) {
          res.writeHead(502, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: `Failed to fetch PR: ${err.message}` })
          )
          return true
        }
      }

      // GET /mr/media?url=<url>&kind=<kind> - Stream or return media (images as data URLs, videos with Range support)
      if (req.method === 'GET' && pathname === '/mr/media') {
        const mediaUrl = searchParams.get('url')
        const kind = searchParams.get('kind')

        // Validate params
        if (!mediaUrl) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing url parameter' })
          )
          return true
        }
        if (!kind || !['image', 'video'].includes(kind)) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing or invalid kind parameter' })
          )
          return true
        }

        // Validate URL
        try {
          new URL(mediaUrl)
          if (!mediaUrl.startsWith('https://')) {
            throw new Error('Only HTTPS URLs are allowed')
          }
        } catch {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Invalid or non-HTTPS URL' })
          )
          return true
        }

        try {
          const result = await mediaLoader.load(mediaUrl, kind)

          if (!result.ok) {
            // Map error reasons to HTTP status codes
            let status = 500
            if (result.reason && result.reason.includes('not a valid address')) status = 400
            if (result.reason && result.reason.includes('only https')) status = 400
            if (result.reason && result.reason.includes('isn\'t loaded')) status = 400
            if (result.reason && result.reason.includes('not found')) status = 404
            if (result.reason && result.reason.includes('timed out')) status = 504
            if (result.reason && result.reason.includes('too large')) status = 413

            res.writeHead(status, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: result.reason })
            )
            return true
          }

          // Handle image responses (data URLs)
          if (result.kind === 'image') {
            const contentType = result.mime || 'application/octet-stream'
            // Decode data URL and send raw bytes
            if (result.dataUrl && result.dataUrl.startsWith('data:')) {
              const [header, data] = result.dataUrl.split(',')
              const mimeMatch = header.match(/data:([^;]+)/)
              const mimeType = mimeMatch ? mimeMatch[1] : contentType
              const buffer = Buffer.from(data, 'base64')
              res.writeHead(200, { 'Content-Type': mimeType, 'Content-Length': buffer.length }).end(buffer)
              return true
            }
            res.writeHead(500, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: 'Invalid image data' })
            )
            return true
          }

          // Handle video responses (stream with Range support)
          if (result.kind === 'video') {
            const mediaFile = mediaFileFor(mediaCacheDir, result.src.split('/').pop())
            if (!mediaFile) {
              res.writeHead(404, { 'Content-Type': 'application/json' }).end(
                JSON.stringify({ ok: false, error: 'Media file not found in cache' })
              )
              return true
            }

            // Get file size
            const stats = await fs.stat(mediaFile.file)
            const totalSize = stats.size

            // Parse Range header
            const rangeHeader = req.headers.range
            if (rangeHeader) {
              const range = parseRange(rangeHeader, totalSize)
              // parseRange returns: range object (valid), -1 (syntactically valid but out of range), or null (malformed)
              if (range === -1) {
                // 416: Range Not Satisfiable
                res.writeHead(416, { 'Content-Range': `bytes */${totalSize}`, 'Content-Type': 'application/json' }).end(
                  JSON.stringify({ ok: false, error: 'Range not satisfiable' })
                )
                return true
              }
              if (range === null) {
                // Malformed Range header, ignore it and serve full file
                res.writeHead(200, {
                  'Content-Type': mediaFile.mime,
                  'Content-Length': totalSize,
                  'Accept-Ranges': 'bytes'
                })
                const stream = createReadStream(mediaFile.file)
                stream.on('error', () => res.destroy())
                stream.pipe(res)
                return true
              }
              // Valid range: 206 Partial Content
              res.writeHead(206, {
                'Content-Type': mediaFile.mime,
                'Content-Length': range.size,
                'Content-Range': `bytes ${range.start}-${range.end}/${totalSize}`,
                'Accept-Ranges': 'bytes'
              })
              const stream = createReadStream(mediaFile.file, { start: range.start, end: range.end })
              stream.on('error', () => res.destroy())
              stream.pipe(res)
              return true
            }

            // Full file response (no Range header)
            res.writeHead(200, {
              'Content-Type': mediaFile.mime,
              'Content-Length': totalSize,
              'Accept-Ranges': 'bytes'
            })
            const stream = createReadStream(mediaFile.file)
            stream.on('error', () => res.destroy())
            stream.pipe(res)
            return true
          }

          res.writeHead(500, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Unknown media kind' })
          )
          return true
        } catch (err) {
          res.writeHead(500, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: `Media loading failed: ${err.message}` })
          )
          return true
        }
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
