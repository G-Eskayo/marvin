import { app, BrowserWindow, ipcMain, dialog, session, shell } from 'electron'
import { instrumentIpc } from './timing.js'
import { installDevSiteCors } from './dev_site_cors.js'
import { join, dirname } from 'path'
import { existsSync, mkdirSync, appendFileSync, statSync } from 'fs'
import { homedir } from 'os'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { listSubsystems, readHistory, buildIndex } from './metrics.js'
import { getReworkStatus, clearReworkCache } from './rework.js'
import { prsForOrderCheck, listPipelinePrs, approveMr, denyMr, fetchTicketContext, sentBackKeys, clearSentBackLabel } from './mr_review.js'
import { readSeenNumbers, markSeen, computeReviewStatus } from './mr_seen.js'
import { readDispatchStatus } from './dispatch_status.js'
import { readHealthStatus, runHealthCheckNow } from './health.js'
import { readOnboardingPlans } from './onboarding.js'
import { readCachedRepos } from './docs.js'
import { createPortfolio } from './portfolio.js'
import { createPortfolioProxy, portfolioHost } from './portfolio_remote.js'
import { listTicketActivity, getTicketTimeline } from './activity.js'
import { getDeviceStatuses } from './devices.js'
import { getQueue } from './queue.js'
import { getConcurrency, setConcurrency, scanNow } from './dispatch_concurrency.js'
import { createMergeOps } from './merge_ops.js'
import { readPrefs } from './prefs.js'
import { guardApprove } from './approve_guard.js'
import { recordRefusal } from '../../webhook-server/refusal_log.js'

const mergeOps = createMergeOps()
import { readRegistry, loadBoard, fetchBoardData, fetchCompletedData, withProjectStatus, defaultStagesFor, defaultLiveNumbers, getEvidence, clearCrossProjectCache, REGISTRY_PATH } from './boards.js'
import { createRelationsService } from './relations_service.js'
import { summarizeBoard, buildCompleted } from './board.js'
import { createTriggerHub, createReconciler, refetchesGithub } from './triggers.js'
import { listOpenPrsAcrossRepos, prListArgs, createListCache, normalizeSeen, canMergeFromDashboard, repoFromPrUrl, MARVIN_REPO } from './mr_repos.js'
import { createIndexer, buildDocsIndex, loadIndex } from './docs_search.js'
import { createDocsService, MASTER_ID } from './docs_service.js'
import { readMergeableRepos, listProfiles, setDispatch, setMergeFromDashboard } from './profiles.js'
import { searchFiles, isRevealable, isLinkable, linkAction } from './files_search.js'
import { readCatalog, readMasterDoc, CATALOG_DIR, MASTER_DOC_PATH } from './catalog.js'
import { STAGES_DIR } from '../../webhook-server/ticket_stages.js'
import { DISPATCH_STATE_PATH } from './dispatch_status.js'
import { createHash } from 'crypto'
import { JOBS_DIR } from './jobs.js'
import { listAgents } from './agents.js'
import { buildWorkingNow } from './working.js'
import { listJobs } from './jobs.js'
import { readTicketAgents } from './ticket_agents.js'
import { getUsageReport } from './usage_report.js'
import { createRefreshServer } from './refresh_server.js'
import { adoptLoginShellPath, adoptSharedGhToken } from './path.js'
import { postTicketInput } from './ticket_input.js'
import { resolveServiceDefaults, resolveDeviceId } from './device_identity.js'

// Every IPC handler below is timed into ~/.claude/logs/dashboard-timing.jsonl (#236); must run before any is registered.
instrumentIpc(ipcMain)

const execFileAsync = promisify(execFile)

adoptLoginShellPath()
adoptSharedGhToken()

// ADR 0032: the webhook-server this app talks to lives on whichever
// machine is the primary automation host, not always localhost -- see
// device_identity.js. Overridable via env for pointing at a real n8n
// webhook once G-Eskayo/marvin#11's "exact n8n node topology" downstream
// work exists; defaults to the reference receiver in dashboard/webhook-server/
// (see its README for the contract).
const { host: defaultWebhookHost } = resolveServiceDefaults()
const MR_WEBHOOK_URL = process.env.MARVIN_MR_WEBHOOK_URL || `http://${defaultWebhookHost}:7878/approve`
// Same reference receiver, second endpoint -- ADR 0025's Deny action.
const MR_DENY_WEBHOOK_URL = process.env.MARVIN_MR_DENY_WEBHOOK_URL || `http://${defaultWebhookHost}:7878/deny`
// Where the webhook-server process forwards its /mr-ready ping (see
// dashboard/webhook-server/refresh_relay.js) so an already-open window
// refreshes immediately instead of waiting on its own fallback poll.
const DASHBOARD_REFRESH_PORT = Number(process.env.MARVIN_DASHBOARD_REFRESH_PORT) || 7879

const ghListOpenPrs = (light) => async (repo) => {
  const { stdout } = await execFileAsync('gh', prListArgs(repo, { light }))
  return JSON.parse(stdout)
}

// Every registered project's open PRs (MR Review spans projects; only marvin's can be merged from
// here -- see mr_repos.js). A failing repo is logged and skipped, never fatal to the list.
async function fetchOpenPrs(light) {
  const { prs, errors } = await listOpenPrsAcrossRepos(readRegistry().map((b) => b.repo), ghListOpenPrs(light))
  for (const e of errors) console.error(`[mr] could not list PRs for ${e.repo}: ${e.message}`)
  return prs
}
// The status dot, the MR list and the merge-order check share one cache; a merge asks for fresh data.
// Real PR changes are announced within ~20s by the change watcher (a 'mr' or 'activity' ping), which clears it, so the
// TTL is only a safety net. At 45s this listing alone cost thousands of requests an hour across the registered repos.
const OPEN_PRS_TTL_MS = 5 * 60_000
const openPrsCache = createListCache({ full: () => fetchOpenPrs(false), light: () => fetchOpenPrs(true) }, OPEN_PRS_TTL_MS)
const listOpenPrs = (opts = {}) => openPrsCache.get(opts)

async function ghIssueView(issueNumber, repo = MARVIN_REPO) {
  const { stdout } = await execFileAsync('gh', ['issue', 'view', String(issueNumber), '--repo', repo, '--json', 'number,title,body'])
  return JSON.parse(stdout)
}

// Raw tickets + PRs per repo, shared by the board view and the relation index, kept for 30s so the two
// (and several tabs) don't each hit GitHub; a trigger or reload clears it.
// Real GitHub changes are announced within ~20s by the change watcher (a cheap REST check) and clear this, so the
// TTL is only a safety net.
const BOARD_DATA_TTL_MS = 5 * 60_000
const boardDataCache = new Map()
async function getBoardData(repo, gh) {
  const hit = boardDataCache.get(repo)
  if (hit && Date.now() - hit.at < BOARD_DATA_TTL_MS) return hit.data
  const data = await fetchBoardData(repo, gh)
  boardDataCache.set(repo, { at: Date.now(), data })
  return data
}

// Event-driven refresh for the Activity tab (CONTEXT.md "Triggers over polling").
const triggerHub = createTriggerHub()
const TRIGGER_MISS_LOG = join(homedir(), '.claude', 'logs', 'trigger-misses.jsonl')
const reconciler = createReconciler({
  lastEmitAt: triggerHub.lastEmitAt,
  record: (miss) => {
    try {
      mkdirSync(dirname(TRIGGER_MISS_LOG), { recursive: true })
      appendFileSync(TRIGGER_MISS_LOG, JSON.stringify(miss) + '\n')
    } catch {
      // the guard must never break the board
    }
  }
})
const boardDigest = (board) =>
  createHash('sha1')
    .update(JSON.stringify(board.columns.map((c) => c.cards.map((k) => [k.number, k.reason, k.prs.map((p) => p.number)]))))
    .digest('hex')

process.env['ELECTRON_DISABLE_SECURITY_WARNINGS'] = 'true'

let mainWindow = null

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 18, y: 18 },
    backgroundColor: '#0f1117',
    vibrancy: 'under-window',
    show: false,
    webPreferences: {
      preload: (() => {
        // electron-vite outputs .cjs when package.json has "type":"module"
        const cjs = join(__dirname, '../preload/index.cjs')
        return existsSync(cjs) ? cjs : join(__dirname, '../preload/index.js')
      })(),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  const devUrl = process.env['ELECTRON_RENDERER_URL']
  if (devUrl) {
    mainWindow.loadURL(devUrl)
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(join(__dirname, '../../out/renderer/index.html'))
  }
}

function registerMetricsHandlers() {
  ipcMain.handle('metrics:index', () => buildIndex())
  ipcMain.handle('metrics:subsystems', () => listSubsystems())
  ipcMain.handle('metrics:history', (_event, subsystem) => readHistory(subsystem))
  ipcMain.handle('metrics:usage', () => getUsageReport())
}

function registerDispatchHandlers() {
  ipcMain.handle('dispatch:status', () => readDispatchStatus())
  ipcMain.handle('devices:status', () => getDeviceStatuses())
  ipcMain.handle('queue:list', () => getQueue())
  ipcMain.handle('dispatch:getConcurrency', () => getConcurrency())
  ipcMain.handle('dispatch:setConcurrency', (_event, settings) => setConcurrency(settings))
  ipcMain.handle('dispatch:scanNow', () => scanNow())
  // The header indicator: dispatched task + every background agent that is mid-run, on this machine.
  ipcMain.handle('working:now', () => buildWorkingNow({ dispatch: readDispatchStatus(), jobs: listJobs() }))
}

function registerHealthHandlers() {
  ipcMain.handle('health:status', () => readHealthStatus())
  ipcMain.handle('health:agents', () => listAgents())
  // Execution profiles (lib/project_profile.py): which projects the pipeline may work on by itself.
  ipcMain.handle('profiles:list', () => listProfiles())
  ipcMain.handle('profiles:setDispatch', async (_event, repo, value) => {
    if (value === 'on') {
      // Same native-dialog defense as Approve: turning this on spends model usage and opens PRs by itself.
      const profile = listProfiles().find((p) => p.repo === repo)
      const { response } = await dialog.showMessageBox(mainWindow, {
        type: 'warning',
        buttons: ['Cancel', 'Turn on'],
        defaultId: 0,
        cancelId: 0,
        message: `Let MARVIN work on ${profile?.name || repo}'s tickets by itself?`,
        detail: `From the next hourly scan, MARVIN will claim this project's ready tickets, run a planning call and an implementation call on ${profile?.machines.join(', ') || 'its machine'} (this spends model usage), and open pull requests for you to review in MR Review. You can turn it off here at any time.`
      })
      if (response !== 1) return { done: false, cancelled: true }
    }
    setDispatch(repo, value)
    return { done: true, cancelled: false }
  })
  // A dry run of the whole path (real worktree, real checks, PR body preview; no model call, no GitHub write).
  ipcMain.handle('profiles:selftest', async (_event, repo) => {
    if (!listProfiles().some((p) => p.repo === repo)) throw new Error(`No profile for ${repo}`)
    try {
      const { stdout } = await execFileAsync(AGENTS_PYTHON, [join(homedir(), '.agents', 'lib', 'project_profile.py'), 'selftest', repo], { timeout: 900_000, maxBuffer: 20 * 1024 * 1024 })
      return { ok: true, output: stdout }
    } catch (err) {
      return { ok: false, output: String(err.stdout || err.stderr || err.message) }
    }
  })
  ipcMain.handle('health:ticketAgents', () => readTicketAgents())
  ipcMain.handle('health:refresh', async () => {
    await runHealthCheckNow(execFileAsync)
    return readHealthStatus()
  })
  ipcMain.handle('health:readiness', () => readOnboardingPlans(readRegistry()))
  ipcMain.handle('health:setMergeFromDashboard', async (_event, repo, value) => {
    if (value === true) {
      const plans = readOnboardingPlans(readRegistry())
      const plan = plans.find((p) => p.repo === repo)
      if (!plan?.offers?.merge_from_dashboard) {
        throw new Error(`${repo} is not ready for merge_from_dashboard`)
      }
      const profile = listProfiles().find((p) => p.repo === repo)
      const { response } = await dialog.showMessageBox(mainWindow, {
        type: 'warning',
        buttons: ['Cancel', 'Turn on'],
        defaultId: 0,
        cancelId: 0,
        message: `Enable merge-from-dashboard for ${profile?.name || repo}?`,
        detail: `Pull requests for this project will become mergeable from MR Review instead of GitHub. You can turn it off here at any time.`
      })
      if (response !== 1) return { done: false, cancelled: true }
    } else {
      const { response } = await dialog.showMessageBox(mainWindow, {
        type: 'question',
        buttons: ['Cancel', 'Turn off'],
        defaultId: 0,
        cancelId: 0,
        message: `Disable merge-from-dashboard for this project?`
      })
      if (response !== 1) return { done: false, cancelled: true }
    }
    setMergeFromDashboard(repo, value)
    return { done: true, cancelled: false }
  })
  ipcMain.handle('health:setDispatch', async (_event, repo, value) => {
    if (value === 'on') {
      const plans = readOnboardingPlans(readRegistry())
      const plan = plans.find((p) => p.repo === repo)
      if (!plan?.offers?.dispatch) {
        throw new Error(`${repo} is not ready for dispatch`)
      }
      const profile = listProfiles().find((p) => p.repo === repo)
      const { response } = await dialog.showMessageBox(mainWindow, {
        type: 'warning',
        buttons: ['Cancel', 'Turn on'],
        defaultId: 0,
        cancelId: 0,
        message: `Let MARVIN work on ${profile?.name || repo}'s tickets by itself?`,
        detail: `From the next hourly scan, MARVIN will claim this project's ready tickets, run a planning call and an implementation call on ${profile?.machines.join(', ') || 'its machine'} (this spends model usage), and open pull requests for you to review in MR Review. You can turn it off here at any time.`
      })
      if (response !== 1) return { done: false, cancelled: true }
    } else {
      const { response } = await dialog.showMessageBox(mainWindow, {
        type: 'question',
        buttons: ['Cancel', 'Turn off'],
        defaultId: 0,
        cancelId: 0,
        message: `Disable dispatch for this project?`
      })
      if (response !== 1) return { done: false, cancelled: true }
    }
    setDispatch(repo, value)
    return { done: true, cancelled: false }
  })
}

function registerActivityHandlers() {
  ipcMain.handle('activity:list', () => listTicketActivity())
  ipcMain.handle('activity:timeline', (_event, number, repo) => getTicketTimeline(number, undefined, repo || null))

  // Project boards: only repos in the registry are fetchable, so the renderer
  // can't make the main process shell out to gh for an arbitrary repo.
  const ghJson = async (args) => (await execFileAsync('gh', args)).stdout
  const assertRegistered = (repo) => {
    if (!readRegistry().some((b) => b.repo === repo)) throw new Error(`No board registered for ${repo}`)
  }
  ipcMain.handle('boards:list', () => withProjectStatus(readRegistry(), readCatalog({ deviceId: deviceId() })))
  ipcMain.handle('boards:load', async (_event, repo, source = 'poll') => {
    assertRegistered(repo)
    const board = await loadBoard(repo, { gh: ghJson, registryRepos: readRegistry(), data: await getBoardData(repo, ghJson), evidence: await getEvidence(repo) })
    reconciler.observe('activity', repo, boardDigest(board), source)
    return board
  })
  ipcMain.handle('boards:summary', async (_event, repo) => {
    assertRegistered(repo)
    return summarizeBoard(await loadBoard(repo, { gh: ghJson, registryRepos: readRegistry(), data: await getBoardData(repo, ghJson), evidence: await getEvidence(repo) }))
  })
  // Completed work (all closed tickets + the PRs that closed them), cached 5 min: it only grows slowly.
  const completedCache = new Map()
  ipcMain.handle('boards:completed', async (_event, repo) => {
    assertRegistered(repo)
    const hit = completedCache.get(repo)
    if (hit && Date.now() - hit.at < 300_000) return hit.value
    const value = buildCompleted(await fetchCompletedData(repo, ghJson))
    completedCache.set(repo, { at: Date.now(), value })
    return value
  })
  ipcMain.handle('boards:ticket', async (_event, repo, number) => {
    assertRegistered(repo)
    const out = await ghJson(['issue', 'view', String(Number(number)), '--repo', repo, '--json', 'number,title,body,labels,url,state,comments'])
    return JSON.parse(out)
  })
  // The owner's reply on a ticket; if the ticket was waiting on it, it goes back in the queue (src/lib/ticket_input.js).
  ipcMain.handle('boards:input', async (_event, repo, number, body) => {
    assertRegistered(repo)
    return postTicketInput({ repo, number, body })
  })
}

let cachedDeviceId
const deviceId = () => (cachedDeviceId === undefined ? (cachedDeviceId = resolveDeviceId()) : cachedDeviceId)
const CATALOG_SCRIPT = join(homedir(), '.agents', 'lib', 'project_catalog.py')
const AGENTS_PYTHON = join(homedir(), '.agents', 'venv', 'bin', 'python')
const FIND_FILE_SCRIPT = join(homedir(), '.claude', 'organize', 'find_file.py') // the `findit` command

function registerDocsHandlers() {
  // The Docs tab is driven by the project catalog (lib/project_catalog.py): every project gets a
  // card, docs come from a local clone when there is one (so uncommitted edits show), else GitHub.
  const docsService = createDocsService({
    getCatalog: () => readCatalog({ deviceId: deviceId() }),
    exec: execFileAsync,
    readMaster: () => readMasterDoc(),
    fallbackRepos: () => readCachedRepos().repos
  })

  // Relationships between tickets, PRs and docs, derived from their text (relations.js). Docs come from
  // local clones when there are any, else the GitHub index; the cache is dropped on the same triggers
  // that refresh the boards and docs.
  const ghForRelations = async (args) => (await execFileAsync('gh', args, { maxBuffer: 50 * 1024 * 1024 })).stdout
  const relations = createRelationsService({
    getRepos: () => readRegistry().map((b) => b.repo),
    getBoardData: (repo) => getBoardData(repo, ghForRelations),
    getDocs: async () => {
      const local = await docsService.localDocs()
      const remote = (loadIndex().docs || []).filter((d) => !local.repos.has(d.repo))
      return [...local.docs, ...remote]
        .filter((d) => d.path !== 'PROJECT.md' && d.repo !== MASTER_ID)
        .map((d) => ({ project: d.repo, path: d.path, label: d.label, content: d.content }))
    },
    getProjects: () => (readCatalog({ deviceId: deviceId() })?.projects || []).filter((p) => p.repo).map((p) => ({ id: p.id, repo: p.repo })),
    getStages: defaultStagesFor,
    getLive: defaultLiveNumbers,
    recheck: () => { boardDataCache.clear(); openPrsCache.invalidate(); clearCrossProjectCache() }
  })
  triggerHub.onTrigger((t) => {
    if (t.topic === 'activity' || t.topic === 'docs') {
      // Local changes (stage files, saved docs) re-derive columns from the cached GitHub data; only a GitHub-side
      // change refetches it. Clearing it on every local write cost ~10,000 requests an hour (2026-10-06).
      if (t.topic === 'activity' && refetchesGithub(t)) { boardDataCache.clear(); openPrsCache.invalidate(); clearCrossProjectCache() }
      relations.invalidate()
    }
  })
  ipcMain.handle('relations:ticket', (_e, repo, number) => relations.forTicket(String(repo), Number(number)))
  ipcMain.handle('relations:doc', (_e, project, filePath) => relations.forDoc(String(project), String(filePath)))
  ipcMain.handle('relations:pr', (_e, repo, number) => relations.forPr(String(repo), Number(number)))
  // MR Review <-> boards, one-to-one: each open PR with its ticket and column; what is waiting on you per project.
  ipcMain.handle('mr:parity', () => relations.parity())
  ipcMain.handle('activity:overview', () => relations.overview())
  ipcMain.handle('relations:context', (_e, project) => relations.context(String(project)))

  let refreshing = null
  function refreshCatalog() {
    if (!refreshing) {
      refreshing = execFileAsync(AGENTS_PYTHON, [CATALOG_SCRIPT, 'refresh'], { timeout: 240_000 })
        .catch(() => {}) // a failed refresh keeps the last good catalog (see project_catalog.refresh)
        .finally(() => (refreshing = null))
    }
    return refreshing
  }

  // Watch where doc state lives so the open view updates itself: each local clone's doc files and
  // git refs (a commit or push changes badges without touching a file), the catalog files, and the
  // master doc. Never `.git/index`: `git status` rewrites it, which would feed a refresh loop.
  const watchedDirs = new Set()
  function watchSources() {
    const watch = (dir, match) => {
      if (watchedDirs.has(`${dir}|${match}`)) return
      watchedDirs.add(`${dir}|${match}`)
      triggerHub.watchFiles('docs', [{ dir, match: typeof match === 'function' ? match : (n) => n === match }])
    }
    for (const dir of docsService.localDirs()) {
      watch(dir, (n) => n === 'CONTEXT.md' || n === 'README.md')
      watch(join(dir, 'docs', 'adr'), (n) => n.endsWith('.md'))
      watch(join(dir, '.git', 'refs', 'heads'), () => true)
      watch(join(dir, '.git', 'refs', 'remotes', 'origin'), () => true)
    }
    watch(CATALOG_DIR, (n) => /^projects\..+\.json$/.test(n) || n === 'overrides.json')
    watch(dirname(MASTER_DOC_PATH), '_WHERE-THINGS-ARE.md')
  }
  watchSources()
  if (!readCatalog({ deviceId: deviceId() })) refreshCatalog().then(watchSources) // first run: build it now

  ipcMain.handle('docs:repos', () => docsService.repos())
  // Full-text search over every card, master and browsable doc; the GitHub part of the index
  // rebuilds in the background when stale, local docs are read live.
  const docsIndexer = createIndexer({
    build: () => buildDocsIndex(execFileAsync, docsService.githubIndexRepos()),
    getLocal: () => docsService.localDocs()
  })
  ipcMain.handle('docs:refresh', async () => {
    await refreshCatalog()
    docsIndexer.reindex()
    watchSources()
    return docsService.repos()
  })
  ipcMain.handle('docs:search', (_event, query, opts) => docsIndexer.search(String(query || ''), opts))
  // "Files on this Mac": the same Spotlight search as the `findit` command, attributed to projects.
  ipcMain.handle('docs:files', (_event, query) =>
    searchFiles(String(query || ''), {
      run: async (q) => (await execFileAsync('/usr/bin/python3', [FIND_FILE_SCRIPT, '--json', q], { timeout: 40_000, maxBuffer: 20 * 1024 * 1024 })).stdout,
      catalog: readCatalog({ deviceId: deviceId() }),
      home: homedir()
    })
  )
  ipcMain.handle('docs:reveal', (_event, filePath) => {
    if (!isRevealable(filePath, homedir()) || !existsSync(filePath)) throw new Error('Not a revealable file')
    shell.showItemInFolder(filePath)
  })
  // A link in the master map: open a folder or document on this Mac, otherwise just show it in Finder (files_search.js).
  ipcMain.handle('docs:openLink', async (_event, filePath) => {
    if (!isLinkable(filePath, homedir()) || !existsSync(filePath)) throw new Error('Not a linkable file')
    if (linkAction(filePath, statSync(filePath).isDirectory()) === 'reveal') return shell.showItemInFolder(filePath)
    const err = await shell.openPath(filePath)
    if (err) throw new Error(err)
  })
  ipcMain.handle('docs:tree', (_event, id) => docsService.tree(id))
  ipcMain.handle('docs:content', (_event, id, filePath) => docsService.content(id, filePath))

  // Portfolio tab (CONTEXT.md "Dashboard app -- Portfolio tab"): component library, design rules, guide,
  // evaluation, images. Dev-only: every write is confined to the portfolio repo's templates/.
  // ADR 0038: the backend runs only on the dev host; anywhere else the same methods go to its webhook server.
  const portfolioAt = portfolioHost({ defaultHost: defaultWebhookHost })
  const localPortfolio = createPortfolio({ exec: execFileAsync })
  const portfolio = portfolioAt.local
    ? localPortfolio
    : createPortfolioProxy({ baseUrl: `http://${portfolioAt.host}:7878/portfolio`, methods: Object.keys(localPortfolio) })
  ipcMain.handle('portfolio:components', () => portfolio.listComponents())
  ipcMain.handle('portfolio:component:save', (_e, name, html, notes) => portfolio.saveComponent(name, html, notes))
  ipcMain.handle('portfolio:component:create', (_e, name, html, notes) => portfolio.createComponent(name, html, notes))
  ipcMain.handle('portfolio:preview-head', () => portfolio.previewHead())
  ipcMain.handle('portfolio:rules', () => portfolio.getRules())
  ipcMain.handle('portfolio:rules:save', (_e, overrides) => portfolio.saveRules(overrides))
  ipcMain.handle('portfolio:guide', () => portfolio.getGuide())
  ipcMain.handle('portfolio:content:templates', () => portfolio.contentTemplates())
  ipcMain.handle('portfolio:content:report', () => portfolio.contentReport())
  ipcMain.handle('portfolio:guide:save', (_e, text) => portfolio.saveGuide(text))
  ipcMain.handle('portfolio:eval:latest', () => portfolio.latestEval())
  ipcMain.handle('portfolio:eval:run', () => portfolio.runEval())
  ipcMain.handle('portfolio:images', () => portfolio.listImages())
  ipcMain.handle('portfolio:image:generate', (_e, slug) => portfolio.generateImage(slug))
  ipcMain.handle('portfolio:image:motifs', () => portfolio.imageMotifs())
  ipcMain.handle('portfolio:image:variants', (_e, slug) => portfolio.imageVariants(slug))
  ipcMain.handle('portfolio:image:variant:new', (_e, slug, motif) => portfolio.newImageVariant(slug, motif))
  ipcMain.handle('portfolio:image:variant:choose', (_e, slug, motif, salt) => portfolio.chooseImageVariant(slug, motif, salt))
  ipcMain.handle('portfolio:project:add', (_e, spec, opts) => portfolio.addProject(spec, opts))
  ipcMain.handle('portfolio:pipeline:status', () => portfolio.pipelineStatus())
  ipcMain.handle('portfolio:pipeline:run', () => portfolio.runPipeline())
  ipcMain.handle('portfolio:elements', () => portfolio.listElements())
  ipcMain.handle('portfolio:element:verify', (_e, id) => portfolio.verifyElement(id))
  ipcMain.handle('portfolio:images:apply', () => portfolio.applyImages())
  ipcMain.handle('portfolio:image:variant:delete', (_e, slug, motif, salt) => portfolio.deleteImageVariant(slug, motif, salt))
  ipcMain.handle('portfolio:image:variant:preview', (_e, slug, motif, salt) => portfolio.variantPreview(slug, motif, salt))
  ipcMain.handle('portfolio:image:preview', (_e, slug) => portfolio.imagePreview(slug))
  ipcMain.handle('portfolio:inventory', () => portfolio.inventory())
  ipcMain.handle('portfolio:inventory:image', (_e, rel) => portfolio.inventoryImage(rel))
  ipcMain.handle('portfolio:inventory:refresh', () => portfolio.refreshInventory())
  ipcMain.handle('portfolio:chrome', () => portfolio.chrome())
  ipcMain.handle('portfolio:page-markup', (_e, slug) => portfolio.pageMarkup(slug))
  ipcMain.handle('portfolio:templates', () => portfolio.listTemplates())
  ipcMain.handle('portfolio:template:source', (_e, id) => portfolio.templateSource(id))
  ipcMain.handle('portfolio:template:specimen', (_e, id) => portfolio.specimen(id))
  ipcMain.handle('portfolio:template:render', (_e, id, data, options) => portfolio.renderTemplate(id, data, options))
  ipcMain.handle('portfolio:project:plan', (_e, data) => portfolio.planProject(data))
  ipcMain.handle('portfolio:reference', () => portfolio.listReference())
  ipcMain.handle('portfolio:reference:markup', (_e, slug) => portfolio.referenceMarkup(slug))
}

function postJson(webhookUrl, body) {
  return fetch(webhookUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
}

function registerMrReviewHandlers() {
  const seenPath = join(app.getPath('userData'), 'mr-seen.json')

  // Tickets sent back for rework carry `needs-reengagement` while their PR stays open. Read from the board data
  // the dashboard already caches (30s), so listing PRs costs no extra GitHub calls.
  const sentBackTickets = async (repos) => {
    const keys = new Set()
    const gh = async (args) => (await execFileAsync('gh', args)).stdout
    for (const repo of repos) {
      try {
        const data = await getBoardData(repo, gh)
        for (const k of sentBackKeys(repo, data.issues)) keys.add(k)
      } catch {
        // one repo failing must not hide the others
      }
    }
    return keys
  }
  // Post-merge rebase results live with the webhook (#225), which may be on the other machine.
  const getRebaseStatus = async () => {
    const res = await fetch(MR_WEBHOOK_URL.replace(/\/approve$/, '/rebase-status'), { signal: AbortSignal.timeout(3000) })
    return res.ok ? res.json() : {}
  }
  ipcMain.handle('mr:list', () => listPipelinePrs(listOpenPrs, { canMerge: (repo) => canMergeFromDashboard(repo, readMergeableRepos()), sentBackTickets, reworkStatus: getReworkStatus, rebaseStatus: getRebaseStatus }))

  // Backs the MR Review tab's status dot -- red/blue/green computed from
  // which pipeline-PR numbers are currently open vs. already marked seen
  // on this machine (see mr_seen.js).
  ipcMain.handle('mr:reviewStatus', async () => {
    const prs = await listPipelinePrs(() => listOpenPrs({ light: true }))
    const keys = prs.map((pr) => pr.key)
    return { status: computeReviewStatus(keys, normalizeSeen(readSeenNumbers(seenPath))), openCount: keys.length }
  })

  ipcMain.handle('mr:markSeen', (_event, prKeys) => {
    markSeen(seenPath, prKeys.filter((k) => typeof k === 'string'))
  })

  // Live-fetches the linked ticket's (and its parent PRD's) requirements/
  // design/tasks for the detail view, per the "link back, don't duplicate"
  // decision in G-Eskayo/marvin#72's evidence schema (ADR 0024).
  ipcMain.handle('mr:ticketContext', (_event, ticketRef, repo = MARVIN_REPO) => {
    if (repo !== MARVIN_REPO && !readRegistry().some((b) => b.repo === repo)) throw new Error(`No board registered for ${repo}`)
    return fetchTicketContext(ticketRef, (n) => ghIssueView(n, repo))
  })

  // marvin's gate is built in; another project needs its profile to opt in. Checked here from the PR url
  // itself, whatever the renderer claims, and again by the webhook (which is the real enforcement).
  const assertMergeable = (url) => {
    const repo = repoFromPrUrl(url)
    if (!repo || !canMergeFromDashboard(repo, readMergeableRepos())) {
      throw Object.assign(new Error(`Merging ${repo || 'this PR'} from the dashboard isn't set up: its project profile has not opted in (merge_from_dashboard). Review it on GitHub.`), { code: 'NO_MERGE_PROFILE' })
    }
  }

  // The actual "unambiguous, no risk of accidental merge from a stray click"
  // requirement (G-Eskayo/marvin#11's acceptance criteria) lives here, not in
  // the renderer -- a native OS-level confirm dialog can't be spoofed by a
  // fast double-click the way a custom in-page confirm affordance could.
  ipcMain.handle('mr:approve', async (_event, { number, url }) => {
    // Checked here, not just greyed out in the UI, so a stale screen can't skip it. Sent-back PRs are marked the same way
    // the list marks them, or a newer PR waits forever on one that can't merge (marvin #209). A refusal is recorded (#215).
    await guardApprove(url, {
      assertMergeable,
      loadPrs: async () => prsForOrderCheck(await listOpenPrs({ fresh: true }), sentBackTickets),
      record: recordRefusal
    })
    if (!mergeOps.start(url)) return { merged: false, cancelled: true, alreadyMerging: true }
    try {
      // The Approve & Merge click is the decision. The native popup is opt-in (prefs.json: confirmMerge) -- the
      // duplicate-start guard above, the merge gate's retest and the base/order checks are what protect a stray click.
      if (readPrefs(join(app.getPath('userData'), 'prefs.json')).confirmMerge) {
        const { response } = await dialog.showMessageBox(mainWindow, {
          type: 'warning',
          buttons: ['Cancel', 'Merge PR'],
          defaultId: 0,
          cancelId: 0,
          message: `Merge PR #${number}?`,
          detail: `This fires the approval webhook and merges ${url} via gh pr merge. This can't be undone from here.`
        })
        if (response !== 1) {
          mergeOps.cancel(url)
          return { merged: false, cancelled: true }
        }
      }
      const result = await approveMr(url, MR_WEBHOOK_URL, postJson)
      mergeOps.finish(url, result)
      openPrsCache.invalidate()  // the list must not keep showing a PR that just merged
      clearReworkCache()
      return { ...result, cancelled: false }
    } catch (err) {
      mergeOps.fail(url, err.message)
      throw err
    }
  })

  ipcMain.handle('mr:mergeState', (_event, url) => mergeOps.get(url))

  // The way out of a wrongly shown "sent back": see clearSentBackLabel (refuses while a rework is running).
  ipcMain.handle('mr:clearSentBack', async (_event, url) => {
    assertMergeable(url)
    const result = await clearSentBackLabel(url, execFileAsync)
    if (result.cleared) openPrsCache.invalidate()
    return result
  })

  // Same native-dialog defense as mr:approve -- both of Deny's terminal
  // actions have real, visible side effects on GitHub (ADR 0025), and
  // "drop" specifically closes the PR and ticket with no undo.
  ipcMain.handle('mr:deny', async (_event, { number, url, ticketNumber, action, reasons, comment }) => {
    assertMergeable(url)
    const isDrop = action === 'drop'
    const { response } = await dialog.showMessageBox(mainWindow, {
      type: 'warning',
      buttons: ['Cancel', isDrop ? 'Drop PR & Ticket' : 'Send Feedback'],
      defaultId: 0,
      cancelId: 0,
      message: isDrop ? `Drop PR #${number} and close its ticket?` : `Send deny feedback on PR #${number}?`,
      detail: isDrop
        ? `This closes ${url} and its ticket via gh. No re-engagement is expected. This can't be undone from here.`
        : `This comments the structured feedback on ${url} and its ticket, then releases the claim for a future review/debug/improve pass.`
    })
    if (response !== 1) {
      return { done: false, cancelled: true }
    }
    await denyMr({ prUrl: url, ticketNumber, action, reasons, comment }, MR_DENY_WEBHOOK_URL, postJson)
    openPrsCache.invalidate()
    return { done: true, cancelled: false }
  })
}

app.whenReady().then(() => {
  installDevSiteCors(session.defaultSession)   // previews need the dev site's web fonts (see dev_site_cors.js)
  registerMetricsHandlers()
  registerMrReviewHandlers()
  registerDispatchHandlers()
  registerHealthHandlers()
  registerDocsHandlers()
  registerActivityHandlers()
  createWindow()

  // Local state: watch where it's stored, so every writer (Python, Node, any chat) is covered.
  mkdirSync(STAGES_DIR, { recursive: true })
  mkdirSync(JOBS_DIR, { recursive: true })
  triggerHub.watchFiles('activity', [
    { dir: STAGES_DIR, match: (n) => n.endsWith('.json') },
    { dir: dirname(DISPATCH_STATE_PATH), match: (n) => n === 'dispatch-state.json' },
    { dir: dirname(REGISTRY_PATH), match: (n) => n === 'registry.json' }
  ])
  // Agents report through run logs; a step landing in that folder refreshes the Health tab's agent list.
  triggerHub.watchFiles('agents', [{ dir: JOBS_DIR, match: (n) => n.endsWith('.json') && !n.startsWith('.') }])
  triggerHub.onTrigger((t) => mainWindow?.webContents.send('trigger', t))

  // External pings (webhook-server): bare = the legacy "MR list changed"; with topics = what changed.
  createRefreshServer((payload = {}) => {
    const topics = Array.isArray(payload.topics) ? payload.topics : ['mr']
    for (const topic of topics) {
      if (topic === 'mr') { openPrsCache.invalidate(); mainWindow?.webContents.send('mr:refresh') }
      else triggerHub.emit(topic, payload.source || 'ping')
    }
  }).listen(DASHBOARD_REFRESH_PORT, '127.0.0.1')

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
