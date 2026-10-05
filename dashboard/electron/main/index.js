import { app, BrowserWindow, ipcMain, dialog, session, shell } from 'electron'
import { installDevSiteCors } from './dev_site_cors.js'
import { join, dirname } from 'path'
import { existsSync, mkdirSync, appendFileSync } from 'fs'
import { homedir } from 'os'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { listSubsystems, readHistory, buildIndex } from './metrics.js'
import { listPipelinePrs, approveMr, denyMr, fetchTicketContext } from './mr_review.js'
import { readSeenNumbers, markSeen, computeReviewStatus } from './mr_seen.js'
import { readDispatchStatus } from './dispatch_status.js'
import { readHealthStatus, runHealthCheckNow } from './health.js'
import { readCachedRepos } from './docs.js'
import { createPortfolio } from './portfolio.js'
import { listTicketActivity, getTicketTimeline } from './activity.js'
import { readRegistry, loadBoard, REGISTRY_PATH } from './boards.js'
import { createTriggerHub, createReconciler } from './triggers.js'
import { createIndexer, buildDocsIndex } from './docs_search.js'
import { createDocsService } from './docs_service.js'
import { searchFiles, isRevealable } from './files_search.js'
import { readCatalog, readMasterDoc, CATALOG_DIR, MASTER_DOC_PATH } from './catalog.js'
import { STAGES_DIR } from '../../webhook-server/ticket_stages.js'
import { DISPATCH_STATE_PATH } from './dispatch_status.js'
import { createHash } from 'crypto'
import { createRefreshServer } from './refresh_server.js'
import { adoptLoginShellPath } from './path.js'
import { resolveServiceDefaults, resolveDeviceId } from './device_identity.js'

const execFileAsync = promisify(execFile)

adoptLoginShellPath()

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

async function listOpenPrs() {
  const { stdout } = await execFileAsync('gh', [
    'pr',
    'list',
    '--repo',
    'G-Eskayo/marvin',
    '--state',
    'open',
    '--json',
    'number,title,url,body'
  ])
  return JSON.parse(stdout)
}

async function ghIssueView(issueNumber) {
  const { stdout } = await execFileAsync('gh', [
    'issue',
    'view',
    String(issueNumber),
    '--repo',
    'G-Eskayo/marvin',
    '--json',
    'number,title,body'
  ])
  return JSON.parse(stdout)
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
}

function registerDispatchHandlers() {
  ipcMain.handle('dispatch:status', () => readDispatchStatus())
}

function registerHealthHandlers() {
  ipcMain.handle('health:status', () => readHealthStatus())
  ipcMain.handle('health:refresh', async () => {
    await runHealthCheckNow(execFileAsync)
    return readHealthStatus()
  })
}

function registerActivityHandlers() {
  ipcMain.handle('activity:list', () => listTicketActivity())
  ipcMain.handle('activity:timeline', (_event, number) => getTicketTimeline(number))

  // Project boards: only repos in the registry are fetchable, so the renderer
  // can't make the main process shell out to gh for an arbitrary repo.
  const ghJson = async (args) => (await execFileAsync('gh', args)).stdout
  const assertRegistered = (repo) => {
    if (!readRegistry().some((b) => b.repo === repo)) throw new Error(`No board registered for ${repo}`)
  }
  ipcMain.handle('boards:list', () => readRegistry())
  ipcMain.handle('boards:load', async (_event, repo, source = 'poll') => {
    assertRegistered(repo)
    const board = await loadBoard(repo, { gh: ghJson })
    reconciler.observe('activity', repo, boardDigest(board), source)
    return board
  })
  ipcMain.handle('boards:ticket', async (_event, repo, number) => {
    assertRegistered(repo)
    const out = await ghJson(['issue', 'view', String(Number(number)), '--repo', repo, '--json', 'number,title,body,labels,url,state,comments'])
    return JSON.parse(out)
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
  ipcMain.handle('docs:tree', (_event, id) => docsService.tree(id))
  ipcMain.handle('docs:content', (_event, id, filePath) => docsService.content(id, filePath))

  // Portfolio tab (CONTEXT.md "Dashboard app -- Portfolio tab"): component library, design rules, guide,
  // evaluation, images. Dev-only: every write is confined to the portfolio repo's templates/.
  const portfolio = createPortfolio({ exec: execFileAsync })
  ipcMain.handle('portfolio:components', () => portfolio.listComponents())
  ipcMain.handle('portfolio:component:save', (_e, name, html, notes) => portfolio.saveComponent(name, html, notes))
  ipcMain.handle('portfolio:component:create', (_e, name, html, notes) => portfolio.createComponent(name, html, notes))
  ipcMain.handle('portfolio:preview-head', () => portfolio.previewHead())
  ipcMain.handle('portfolio:rules', () => portfolio.getRules())
  ipcMain.handle('portfolio:rules:save', (_e, overrides) => portfolio.saveRules(overrides))
  ipcMain.handle('portfolio:guide', () => portfolio.getGuide())
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

  ipcMain.handle('mr:list', () => listPipelinePrs(listOpenPrs))

  // Backs the MR Review tab's status dot -- red/blue/green computed from
  // which pipeline-PR numbers are currently open vs. already marked seen
  // on this machine (see mr_seen.js).
  ipcMain.handle('mr:reviewStatus', async () => {
    const prs = await listPipelinePrs(listOpenPrs)
    const numbers = prs.map((pr) => pr.number)
    return { status: computeReviewStatus(numbers, readSeenNumbers(seenPath)), openCount: numbers.length }
  })

  ipcMain.handle('mr:markSeen', (_event, prNumbers) => {
    markSeen(seenPath, prNumbers)
  })

  // Live-fetches the linked ticket's (and its parent PRD's) requirements/
  // design/tasks for the detail view, per the "link back, don't duplicate"
  // decision in G-Eskayo/marvin#72's evidence schema (ADR 0024).
  ipcMain.handle('mr:ticketContext', (_event, ticketRef) => fetchTicketContext(ticketRef, ghIssueView))

  // The actual "unambiguous, no risk of accidental merge from a stray click"
  // requirement (G-Eskayo/marvin#11's acceptance criteria) lives here, not in
  // the renderer -- a native OS-level confirm dialog can't be spoofed by a
  // fast double-click the way a custom in-page confirm affordance could.
  ipcMain.handle('mr:approve', async (_event, { number, url }) => {
    const { response } = await dialog.showMessageBox(mainWindow, {
      type: 'warning',
      buttons: ['Cancel', 'Merge PR'],
      defaultId: 0,
      cancelId: 0,
      message: `Merge PR #${number}?`,
      detail: `This fires the approval webhook and merges ${url} via gh pr merge. This can't be undone from here.`
    })
    if (response !== 1) {
      return { merged: false, cancelled: true }
    }
    const result = await approveMr(url, MR_WEBHOOK_URL, postJson)
    return { ...result, cancelled: false }
  })

  // Same native-dialog defense as mr:approve -- both of Deny's terminal
  // actions have real, visible side effects on GitHub (ADR 0025), and
  // "drop" specifically closes the PR and ticket with no undo.
  ipcMain.handle('mr:deny', async (_event, { number, url, ticketNumber, action, reasons, comment }) => {
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
  triggerHub.watchFiles('activity', [
    { dir: STAGES_DIR, match: (n) => n.endsWith('.json') },
    { dir: dirname(DISPATCH_STATE_PATH), match: (n) => n === 'dispatch-state.json' },
    { dir: dirname(REGISTRY_PATH), match: (n) => n === 'registry.json' }
  ])
  triggerHub.onTrigger((t) => mainWindow?.webContents.send('trigger', t))

  // External pings (webhook-server): bare = the legacy "MR list changed"; with topics = what changed.
  createRefreshServer((payload = {}) => {
    const topics = Array.isArray(payload.topics) ? payload.topics : ['mr']
    for (const topic of topics) {
      if (topic === 'mr') mainWindow?.webContents.send('mr:refresh')
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
