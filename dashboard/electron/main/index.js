import { app, BrowserWindow, ipcMain, dialog, session, shell, protocol, net, nativeImage, Notification } from 'electron'
import { pathToFileURL } from 'url'
import { instrumentIpc } from './timing.js'
import { installDevSiteCors } from './dev_site_cors.js'
import { join, dirname } from 'path'
import { existsSync, mkdirSync, appendFileSync, statSync, readFileSync } from 'fs'
import { homedir } from 'os'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { listSubsystems, readHistory, buildIndex } from './metrics.js'
import { getReworkStatus, clearReworkCache } from './rework.js'
import { createGithubState, repoOfSource, gateCooldownUntil } from './github_state.js'
import { startCheckWatch, createCheckProbe, createTreeProbe, startChangeWatch, createGithubProbe } from '../../webhook-server/gh_watch.js'
import { createStackRetarget } from './stack_retarget.js'
import { prsForOrderCheck, listPipelinePrs, denyMr, fetchTicketContext, sentBackKeys, clearSentBackLabel } from './mr_review.js'
import { approveMrStream } from './approve_stream.js'
import { readSeenNumbers, markSeen, computeReviewStatus } from './mr_seen.js'
import { readDispatchStatus } from './dispatch_status.js'
import { readHealthStatus, runHealthCheckNow, rebuildCodeGraph } from './health.js'
import { buildBootData, createBootGate } from './boot_data.js'
import { readOnboardingPlans } from './onboarding.js'
import { readCachedRepos } from './docs.js'
import { createPortfolio } from './portfolio.js'
import { createPortfolioProxy, portfolioHost } from './portfolio_remote.js'
import { listTicketActivity, getTicketTimeline } from './activity.js'
import { getDeviceStatuses } from './devices.js'
import { getQueue, clearQueueCache } from './queue.js'
import { getConcurrency, setConcurrency, scanNow } from './dispatch_concurrency.js'
import { createMergeOps } from './merge_ops.js'
import { readPrefs } from './prefs.js'
import { guardApprove } from './approve_guard.js'
import { recordRefusal } from '../../webhook-server/refusal_log.js'
import { sendBackForOptions } from './decisions_submit.js'
import { createLocalFirst, coalesce, createIssueReader, createRepoHeadCheck } from './local_first.js'
import { createMrActions } from './mr_actions.js'

const mergeOps = createMergeOps()
// marvin#568: every change to a merge op is pushed to the renderer (the card subscribes; it reads once on mount).
function pushMergeOp(url, op) {
  if (op) mainWindow?.webContents.send('mr:mergeEvent', url, op)
}
// A merge running here whose PR GitHub now calls merged was merged on GitHub by hand: end it as "Merged on GitHub"
// (merge_ops.githubChanged). Asked only on a change trigger, once per merging op; nothing while no merge runs.
const viewPrState = async (url) => JSON.parse((await execFileAsync('gh', ['pr', 'view', url, '--json', 'state'])).stdout)
function checkMergedElsewhere(repo, only = null) {
  mergeOps.githubChanged(repo, viewPrState, Date.now(), only)
    .then((urls) => urls.forEach((u) => pushMergeOp(u, mergeOps.get(u))))
    .catch(() => {})
}
import { readRegistry, loadBoard, fetchBoardData, fetchCompletedData, withProjectStatus, defaultStagesFor, defaultLiveNumbers, getEvidence, clearCrossProjectCache, REGISTRY_PATH } from './boards.js'
import { createRelationsService } from './relations_service.js'
import { summarizeBoard, buildCompleted } from './board.js'
import { createTriggerHub, createReconciler, refetchesGithub } from './triggers.js'
import { createMrHistory, mergedPrArgs, readSavedMerged } from './mr_history.js'
import { createProjectProgress } from './project_progress.js'
import { appendError } from './error_log.js'
import { listOpenPrsAcrossRepos, prListArgs, normalizeSeen, canMergeFromDashboard, repoFromPrUrl, MARVIN_REPO, pendingCheckHeads } from './mr_repos.js'
import { createIndexer, buildDocsIndex, loadIndex } from './docs_search.js'
import { createDocsService, MASTER_ID } from './docs_service.js'
import { createCloneFreshener } from './clone_freshen.js'
import { createPdfText } from './pdf_text.js'
import { createSavedDocs } from './docs_saved.js'
import { readMergeableRepos, readUiPaths, listProfiles, setDispatch, setMergeFromDashboard, readGoals, PROFILES_DIR } from './profiles.js'
import { searchFiles, isRevealable, isLinkable, linkAction } from './files_search.js'
import { safeExternalUrl } from '../../src/lib/pdf_nav.js'
import { openLink, windowOpenHandler } from './external_links.js'
import { readOutboxFile, readOutboxImage, outboxRevealPath, outboxOpenPath, outboxRoot, listOutboxDir, summarizeOutbox, outboxPreview } from './outbox.js'
import { createDeliverables } from './deliverables.js'
import { createThumbs } from './thumbs.js'
import { docsTextFor, maxNumbers, docsClickHandlers } from './docs_handlers.js'
import { readCatalog, readMasterDoc, readOverrides, CATALOG_DIR, MASTER_DOC_PATH } from './catalog.js'
import { STAGES_DIR } from '../../webhook-server/ticket_stages.js'
import { DISPATCH_STATE_PATH } from './dispatch_status.js'
import { createHash } from 'crypto'
import { JOBS_DIR } from './jobs.js'
import { openMarvinSession } from './marvin_session.js'
import * as instance from './instance.js'
import { readSupportState, badgeCount, runSupport, ensureSupportDir, SUPPORT_DIR, supportNotices } from './support.js'
import { supportWatcher, startAppSupportWatch } from '../../webhook-server/support_sync.js'
import { createProposals } from './proposals.js'
const proposalsStore = createProposals()
import { openDevSite } from './dev_site_chrome.js'
import { listAgents } from './agents.js'
import { buildWorkingNow } from './working.js'
import { listJobs } from './jobs.js'
import { readTicketAgents } from './ticket_agents.js'
import { getUsageReport } from './usage_report.js'
import { startRefreshServer, parseRefreshPort } from './refresh_server.js'
import { isEvidenceCapture, installCaptureGuard } from './capture_mode.js'
import { adoptLoginShellPath, adoptSharedGhToken, useGhGate } from './path.js'
import { postTicketInput } from './ticket_input.js'
import { createImageLoader, mediaFileFor } from './pr_images.js'
import { resolveServiceDefaults, resolveDeviceId, peerHosts } from './device_identity.js'
import { createHelpersReader } from './chat_helpers.js'

// The pipeline's screenshot copy runs unattended beside the real dashboard: log, never show a modal (#384).
if (isEvidenceCapture(process.env)) installCaptureGuard(process)

// Every IPC handler below is timed into ~/.claude/logs/dashboard-timing.jsonl (#236); must run before any is registered.
instrumentIpc(ipcMain)

const execFileAsync = promisify(execFile)

adoptLoginShellPath()
adoptSharedGhToken()
useGhGate()

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
// 0 = ephemeral (the evidence-capture copy); junk falls back to 7879.
const DASHBOARD_REFRESH_PORT = parseRefreshPort(process.env.MARVIN_DASHBOARD_REFRESH_PORT)

const ghListOpenPrs = (light) => async (repo) => {
  const { stdout } = await execFileAsync('gh', prListArgs(repo, { light }))
  return JSON.parse(stdout)
}

// The dashboard's memory of GitHub (github_state.js, #318): every GitHub read below is answered from the last-known
// state of its repo until the change watch says that repo changed, the person's own action needs fresh data, or a
// 30-minute safety refresh. Tab switches and timers never reach GitHub on their own.
const githubState = createGithubState()
// Project goals (profiles in the private instance, ADR 0071): read once, and again only after a profile file changes
// (the 'goals' trigger below). O(projects) per read; no polling. A public engine install has no instance dir: [].
let goalsCache = null
const currentGoals = () => (goalsCache ||= readGoals())
const MR_HISTORY_PATH = join(homedir(), '.claude', 'logs', 'mr-history.json')
// A change somewhere: re-read just that repo when the ping says which, else everything.
function githubChanged(source) {
  const repo = repoOfSource(source)
  if (repo) githubState.changed(repo)
  else githubState.changedAll()
  clearCrossProjectCache()
}

// Every registered project's open PRs (MR Review spans projects; only marvin's can be merged from
// here -- see mr_repos.js). A failing repo is logged and skipped, never fatal to the list. Each repo's list comes
// from memory unless that repo changed, so the status dot (every 2 min) and the MR list cost nothing while idle.
// A full listing also answers a light one. `fresh` (a merge) re-reads every repo.
async function fetchOpenPrs(light, fresh = false) {
  const perRepo = (repo) => {
    const full = () => githubState.get('prs', repo, () => ghListOpenPrs(false)(repo), { fresh })
    if (!light) return full()
    return githubState.get('prs-light', repo, () => ghListOpenPrs(true)(repo), { fresh })
  }
  const repos = readRegistry().map((b) => b.repo)
  const listed = await listOpenPrsAcrossRepos(repos, perRepo, { listedAt: (repo) => githubState.fetchedAt(light ? 'prs-light' : 'prs', repo) })
  const errors = listed.errors
  // A merge running here whose PR is no longer in its repo's open list (and that repo was read fine) was closed or
  // merged elsewhere: ask GitHub about just those (marvin#568).
  const open = new Set(listed.prs.map((p) => p.url))
  const failed = new Set(errors.map((e) => e.repo))
  const gone = mergeOps.mergingUrls().filter((u) => !open.has(u) && !failed.has(repoFromPrUrl(u)))
  if (gone.length) checkMergedElsewhere(null, new Set(gone))
  // "Last checked" on a PR's checks (marvin#555): the check watch's last probe of its commit, if later than the list read.
  const prs = listed.prs.map((p) => {
    const probed = p.headRefOid ? checkWatch?.watcher.checkedAt(p.repo, p.headRefOid) : null
    return { ...p, checkedAt: Math.max(p.listedAt || 0, probed || 0) || null }
  })
  for (const e of errors) {
    console.error(`[mr] could not list PRs for ${e.repo}: ${e.message}`)
    appendError({ source: 'dashboard:mr:list', message: `could not list PRs for ${e.repo}`, raw: e.message })
  }
  // #422: what the Open list is built from, so it can say "couldn't reach GitHub" instead of looking empty.
  const stale = githubState.failing(light ? 'prs-light' : 'prs').filter((f) => !errors.some((e) => e.repo === f.repo))
  const all = [...errors.map((e) => ({ repo: e.repo, message: e.message })), ...stale]
  prFetch = { errors: all, projects: repos.length, lastGoodAt: all.length ? prFetch.lastGoodAt : Date.now() }
  return prs
}
let prFetch = { errors: [], projects: 0, lastGoodAt: null }
// Check watch (marvin#555, replacing #554's 90 s re-read): while a cached PR list shows checks running, ask GitHub about
// each such commit's checks every 20 s with an ETag (a 304 is free). A real change re-reads just that repo's list and
// tells an open MR Review to refresh. Reads only what is already in memory to decide what to watch. Started when the
// app is ready.
let checkWatch = null
function startPrCheckWatch() {
  checkWatch = startCheckWatch({
    getHeads: () => githubState.peek('prs').flatMap(({ repo, value }) => pendingCheckHeads(repo, value)),
    probe: createCheckProbe(),
    onChange: (repo) => {
      githubChanged(`github:${repo}`)
      mainWindow?.webContents.send('mr:refresh')
      checkMergedElsewhere(repo)
    },
    skip: () => Date.now() < gateCooldownUntil()
  })
}
const listOpenPrs = ({ light = false, fresh = false } = {}) => fetchOpenPrs(light, fresh)
// Sent-back tickets' rework status spans every project (lib/rework_status.py reads GitHub): same rule as the queue.
// #324: at most one run every 5 minutes, however many change pings arrive (each run reads every project).
const reworkFromMemory = () => githubState.get('rework', null, () => { clearReworkCache(); return getReworkStatus() }, { safetyMs: 10 * 60_000, minIntervalMs: 5 * 60_000 })

async function ghIssueView(issueNumber, repo = MARVIN_REPO) {
  const { stdout } = await execFileAsync('gh', ['issue', 'view', String(issueNumber), '--repo', repo, '--json', 'number,title,body'])
  return JSON.parse(stdout)
}

// Raw tickets + PRs per repo, shared by the board view and the relation index: from memory until that repo changes.
function getBoardData(repo, gh) {
  return githubState.get('board', repo, () => fetchBoardData(repo, gh))
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
  // Links that would open a new window go to Chrome, where Gil is signed in (external_links.js).
  mainWindow.webContents.setWindowOpenHandler(windowOpenHandler((url) => openLink(url, { openExternal: shell.openExternal })))

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
  // The queue and running list span every project and come from GitHub labels: from memory until anything changes,
  // with a 10-minute safety refresh (the Python helper keeps its own 60 s cache, so it is cleared before a real read).
  ipcMain.handle('queue:list', () => githubState.get('queue', null, () => { clearQueueCache(); return getQueue() }, { safetyMs: 10 * 60_000 }))
  ipcMain.handle('dispatch:getConcurrency', () => getConcurrency())
  ipcMain.handle('dispatch:setConcurrency', (_event, settings) => setConcurrency(settings))
  ipcMain.handle('dispatch:scanNow', () => scanNow())
  // The header indicator: dispatched task + every background agent that is mid-run, on this machine.
  ipcMain.handle('working:now', () => buildWorkingNow({ dispatch: readDispatchStatus(), jobs: listJobs() }))
}

function registerSessionHandlers() {
  // The MARVIN button (marvin#228): a ready MARVIN session in WezTerm on this Mac.
  ipcMain.handle('marvin:openSession', (_event, request) => openMarvinSession(request))
  // Support link (ADR 0073). Every action is checked against this install's own support repos in support.js.
  ipcMain.handle('support:config', () => instance.support())
  ipcMain.handle('support:state', () => {
    const { role } = instance.support()
    const state = readSupportState()
    return { role, ...state, badge: badgeCount(role, state) }
  })
  ipcMain.handle('support:act', (_event, cmd, request) => runSupport(cmd, request, { repos: instance.support().repos }))
  // MR Review → Proposals (#102, ADR 0068): read and act through lib/proposals.py only.
  ipcMain.handle('proposals:list', () => proposalsStore.list())
  ipcMain.handle('proposals:act', (_event, id, action, args) => proposalsStore.act(id, action, args))
  // The Portfolio tab's "Open dev site" button (marvin#377): reuses the dev site's Chrome tab if one is open. The
  // renderer sends no URL; only the dev site can be opened this way.
  ipcMain.handle('portfolio:openDevSite', () => openDevSite())
}

// Boot sequence (#431): plays on the first window load of each app launch; reloads skip it.
const bootGate = createBootGate()

function registerHealthHandlers() {
  ipcMain.handle('boot:data', () => (bootGate() ? { show: true, data: buildBootData() } : { show: false }))
  ipcMain.handle('health:status', () => readHealthStatus())
  ipcMain.handle('health:agents', () => listAgents())
  // Execution profiles (lib/project_profile.py): which projects the pipeline may work on by itself.
  ipcMain.handle('profiles:list', () => listProfiles())
  ipcMain.handle('profiles:goals', () => currentGoals())
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
  ipcMain.handle('health:rebuildGraph', async () => {
    const result = await rebuildCodeGraph(execFileAsync)
    return { ...result, status: readHealthStatus() }
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
  // Chat helpers, this Mac's and the other's (#612). This Mac's arrive by the 'agents' trigger (same jobs folder).
  let peers = null // the registry changes rarely and the app is relaunched on every rebuild
  const readHelpers = createHelpersReader({ peers: () => (peers ||= peerHosts()) })
  ipcMain.handle('activity:helpers', () => readHelpers())
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
  // Completed work (all closed tickets + the PRs that closed them): from memory until that repo changes.
  ipcMain.handle('boards:completed', async (_event, repo) => {
    assertRegistered(repo)
    return githubState.get('completed', repo, async () => buildCompleted(await fetchCompletedData(repo, ghJson)))
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
  // #565: GitHub-only projects read a saved copy on every click; opening one sends a single conditional request.
  // The first copy is seeded from the search index's text (read once, only for a repo with no saved file yet).
  let seedIndex = null
  const savedDocs = createSavedDocs({
    probe: createTreeProbe(),
    exec: execFileAsync,
    skip: () => Date.now() < gateCooldownUntil(),
    seed: (repo) => {
      const rec = (readCatalog({ deviceId: deviceId() })?.projects || []).find((p) => p.repo === repo)
      if (!rec) return null
      seedIndex = seedIndex || loadIndex()
      return { at: seedIndex.generated_at, docs: seedIndex.docs.filter((d) => d.repo === rec.id) }
    }
  })
  // #570: outbox items matched to projects from text (deliverables.js). The match map is saved, so the tab draws it at
  // once; the outbox trigger re-matches only what changed. Its context reads only what is local or already in memory:
  // the catalog, overrides, each project's docs (local clone or saved copy) and the board numbers github_state holds.
  let docsTextCache = null
  // #611: text inside PDF deliverables, read once per PDF by pdf.js in the background and cached by content hash
  // (pdf_text.js); when new text lands, the search re-reads the deliverables' text once.
  const pdfText = createPdfText({
    autoDrain: true,
    onReady: () => {
      deliverables.invalidateSearch()
      docsIndexer.localChanged()
    }
  })
  const deliverables = createDeliverables({
    pdfText,
    getContext: () => {
      const projects = readCatalog({ deviceId: deviceId() })?.projects || []
      docsTextCache = docsTextCache || docsTextFor(projects, { saved: savedDocs })
      return { projects, overrides: readOverrides(), maxNumber: maxNumbers(githubState.peek('board')), docsText: docsTextCache }
    }
  })
  // #611: clean local clones are fast-forwarded in the background so the search sees what is on GitHub; a clone with
  // work in it is left alone and searched from its saved GitHub copy (clone_freshen.js, docs_service.js localDocs).
  const freshener = createCloneFreshener({ exec: execFileAsync })
  const docsService = createDocsService({
    midWork: (dir) => freshener.midWork(dir),
    getCatalog: () => readCatalog({ deviceId: deviceId() }),
    exec: execFileAsync,
    readMaster: () => readMasterDoc(),
    fallbackRepos: () => readCachedRepos().repos,
    saved: savedDocs,
    deliverables,
    onStatesChanged: () => triggerHub.emit('docs-states', 'git-status')
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
        .filter((d) => d.path !== 'PROJECT.md' && d.repo !== MASTER_ID && d.kind !== 'deliverable') // outbox items are search-only (#570)
        .map((d) => ({ project: d.repo, path: d.path, label: d.label, content: d.content }))
    },
    getProjects: () => (readCatalog({ deviceId: deviceId() })?.projects || []).filter((p) => p.repo).map((p) => ({ id: p.id, repo: p.repo })),
    getStages: defaultStagesFor,
    getLive: defaultLiveNumbers,
    // Only the repos parity named. With none named there is nothing specific to re-read, and marking all 13 changed
    // re-listed every repo (the fan-out local-first actions removed, 2026-10-21).
    recheck: (repos = []) => repos.forEach((r) => githubChanged(`github:${r}`))
  })
  triggerHub.onTrigger((t) => {
    if (t.topic === 'activity' || t.topic === 'docs') {
      // Local changes (stage files, saved docs) re-derive columns from the cached GitHub data; only a GitHub-side
      // change refetches it. Clearing it on every local write cost ~10,000 requests an hour (2026-10-06).
      if (t.topic === 'activity' && refetchesGithub(t)) githubChanged(t.source)
      relations.invalidate()
    }
  })
  ipcMain.handle('relations:ticket', (_e, repo, number) => relations.forTicket(String(repo), Number(number)))
  ipcMain.handle('relations:doc', (_e, project, filePath) => relations.forDoc(String(project), String(filePath)))
  ipcMain.handle('relations:pr', (_e, repo, number) => relations.forPr(String(repo), Number(number)))
  // MR Review <-> boards, one-to-one: each open PR with its ticket and column; what is waiting on you per project.
  ipcMain.handle('mr:parity', () => relations.parity())
  ipcMain.handle('activity:overview', () => relations.overview())
  ipcMain.handle('activity:needsYou', () => relations.needsYou())
  // Activity ▸ Projects (marvin#625's progress strip): built from memory and local files only, no GitHub call. Merges
  // are the Merged view's saved list plus the merge server's own record (local HTTP), deduped by URL.
  const progress = createProjectProgress({
    goals: currentGoals,
    overview: () => relations.overview(),
    peekBoards: () => githubState.peek('board'),
    stagesFor: defaultStagesFor,
    boards: () => withProjectStatus(readRegistry(), readCatalog({ deviceId: deviceId() })),
    savedMerged: () => readSavedMerged(MR_HISTORY_PATH),
    serverMerges: () =>
      fetch(MR_WEBHOOK_URL.replace(/\/approve$/, '/merge-history'), { signal: AbortSignal.timeout(3000) })
        .then((r) => (r.ok ? r.json() : {}))
        .then((h) => (h.merges || []).map((m) => ({ url: m.pr_url, at: m.t })))
  })
  ipcMain.handle('activity:progress', () => progress())
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

  // The outbox trigger (#570): every changed path in a burst is collected, then only those top-level items re-match.
  const outboxChanged = new Set()
  triggerHub.watchFiles('outbox', [{ dir: outboxRoot(), recursive: true, match: (n) => (outboxChanged.add(n), true) }])
  triggerHub.onTrigger((t) => {
    if (t.topic === 'docs') docsTextCache = null // a doc changed: the docs-phrase tier re-reads, the map rebuilds in the background
    // GitHub-side board changes can add ticket numbers (the number tier); a refresh with nothing new is a few stats.
    const boards = t.topic === 'activity' && refetchesGithub(t)
    if (t.topic !== 'outbox' && t.topic !== 'docs' && !boards) return
    const names = t.topic === 'outbox' ? [...outboxChanged] : null
    outboxChanged.clear()
    setImmediate(() => {
      try {
        deliverables.refresh(names)
      } catch (err) {
        console.error('[docs] could not re-match the outbox:', err)
      }
    })
  })
  // Saved state first: the tab draws the saved map; this one background pass catches what changed while the app was closed.
  setImmediate(() => {
    try {
      deliverables.refresh()
      triggerHub.emit('outbox', 'startup')
    } catch (err) {
      console.error('[docs] could not match the outbox:', err)
    }
  })

  // Full-text search over every card, master and browsable doc; the GitHub part of the index
  // rebuilds in the background when stale, local docs are read live.
  // The automatic build (empty or stale index) reads the saved copies only, so typing a search never reaches GitHub;
  // the explicit Refresh (docs:refresh) is the online build: one conditional request per GitHub-only repo (#565).
  const buildIndex = (online) => buildDocsIndex(execFileAsync, docsService.githubIndexRepos(), undefined, { saved: savedDocs, offline: !online })
  const docsIndexer = createIndexer({
    build: () => buildIndex(false),
    getLocal: () => docsService.localDocs()
  })
  // Every Docs click, from one table (docs_handlers.js; test/docs_clicks_network.test.js counts their network calls).
  // Card covers are downscaled once and cached (thumbs.js); Electron's own image code does the resize, nothing external.
  const thumbs = createThumbs({
    resize: (buf, width) => {
      const img = nativeImage.createFromBuffer(buf)
      if (img.isEmpty()) return null
      return (img.getSize().width > width ? img.resize({ width, quality: 'good' }) : img).toJPEG(80)
    }
  })
  const outboxReads = { list: listOutboxDir, summary: summarizeOutbox, preview: outboxPreview, content: readOutboxFile, image: readOutboxImage, thumb: thumbs.thumb }
  for (const [channel, fn] of Object.entries(docsClickHandlers({ docsService, docsIndexer, outbox: outboxReads }))) {
    ipcMain.handle(channel, (_event, ...args) => fn(...args))
  }
  // A docs change refreshes the search's in-memory copy of local docs in the background (docs_search.js).
  triggerHub.onTrigger((t) => { if (t.topic === 'docs' || t.topic === 'outbox') docsIndexer.localChanged() })
  // #611: freshen clean clones when the Docs tab opens (docs:freshen) and on the docs change watch. No polling loop:
  // the freshener itself runs each project at most once per 30 min. A clone left alone with work in it gets one
  // conditional request for its saved GitHub copy (#565), which its search then reads.
  async function freshenClones() {
    try {
      const { updated, midWork } = await freshener.freshen(docsService.freshenTargets())
      const projects = readCatalog({ deviceId: deviceId() })?.projects || []
      for (const id of midWork) {
        const rec = projects.find((p) => p.id === id)
        if (rec?.repo) await savedDocs.revalidate(rec.repo).catch(() => null)
      }
      if (updated.length || midWork.length) docsIndexer.localChanged()
      return { updated, midWork }
    } catch (err) {
      console.error('[docs] could not freshen clones:', err)
      return { updated: [], midWork: [] }
    }
  }
  triggerHub.onTrigger((t) => { if (t.topic === 'docs') freshenClones() })
  ipcMain.handle('docs:freshen', () => freshenClones())
  ipcMain.handle('docs:refresh', async () => {
    await refreshCatalog()
    docsIndexer.reindex(() => buildIndex(true))
    watchSources()
    return docsService.repos()
  })
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
  // Once per open of a GitHub-only project (#565): one conditional request; a 304 is free, a change comes back in place.
  ipcMain.handle('docs:revalidate', async (_event, id) => {
    const r = await docsService.revalidate(String(id))
    if (r.status === 'changed') docsIndexer.reindex() // the search sees the new text (saved copies, no network)
    return r
  })


  // Deliverables (the outbox, shown inside Docs since #570): read-only, local, one folder at a time.
  // An image a markdown file embeds, resolved against that file's folder; read-only, never outside the outbox (#402).
  ipcMain.handle('outbox:reveal', (_event, relPath) => shell.showItemInFolder(outboxRevealPath(relPath)))
  // A link clicked inside a PDF: only http/https/mailto go to the default browser or mail app (pdf_nav.js
  // safeExternalUrl, checked again here so a compromised page can't widen it). Never file:, javascript: or custom schemes.
  ipcMain.handle('outbox:openLink', async (_event, url) => {
    const safe = safeExternalUrl(url)
    if (!safe) throw new Error('Only web and mail links open from a PDF')
    await shell.openExternal(safe)
  })
  // Open in Preview (PDFs only, see outboxOpenPath), like docs:openLink; same guard as every outbox read.
  ipcMain.handle('outbox:open', async (_event, relPath) => {
    const err = await shell.openPath(outboxOpenPath(relPath))
    if (err) throw new Error(err)
  })

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
  ipcMain.handle('portfolio:flux:styles', () => portfolio.imageStyleCatalog())
  ipcMain.handle('portfolio:flux:variants', (_e, slug) => portfolio.fluxVariants(slug))
  ipcMain.handle('portfolio:flux:generate', (_e, slug, subject, style, mood) => portfolio.generateFluxVariant(slug, subject, style, mood))
  ipcMain.handle('portfolio:flux:choose', (_e, slug, seed) => portfolio.chooseFluxVariant(slug, seed))
  ipcMain.handle('portfolio:flux:delete', (_e, slug, seed) => portfolio.deleteFluxVariant(slug, seed))
  ipcMain.handle('portfolio:flux:preview', (_e, slug, seed, type) => portfolio.fluxVariantPreview(slug, seed, type))
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
  // Tickets already closed, from the same board data in memory (no extra GitHub calls): a PR still open for one is
  // probably a duplicate (#326).
  const closedTickets = async (repos) => {
    const keys = new Set()
    const gh = async (args) => (await execFileAsync('gh', args)).stdout
    for (const repo of repos) {
      try {
        const data = await getBoardData(repo, gh)
        for (const i of data.issues) if (i.state === 'CLOSED') keys.add(`${repo}#${i.number}`)
      } catch {
        // one repo failing must not hide the others
      }
    }
    return keys
  }
  // Post-merge rebase results live with the webhook (#225), which may be on the other machine.
  // Auto-merge's shadow state (#341) lives with the mini's merge server, like the rebase results.
  const getAutoMergeShadow = async () => {
    const res = await fetch(MR_WEBHOOK_URL.replace(/\/approve$/, '/auto-merge-shadow'), { signal: AbortSignal.timeout(3000) })
    return res.ok ? res.json() : {}
  }
  // MR Review's Merged view (#419): saved history at once ({fresh:false}), or an incremental read of GitHub plus the
  // merge server's own record of merges and refused Approves ({fresh:true}).
  const mrHistory = createMrHistory({
    repos: () => readRegistry().map((b) => b.repo),
    ghList: async (repo, since) => JSON.parse((await execFileAsync('gh', mergedPrArgs(repo, since))).stdout || '[]'),
    webhookHistory: async () => {
      const res = await fetch(MR_WEBHOOK_URL.replace(/\/approve$/, '/merge-history'), { signal: AbortSignal.timeout(5000) })
      if (!res.ok) throw new Error(`merge server answered ${res.status}`)
      return res.json()
    },
    openPrs: () => listOpenPrs({ light: true }),
    cachePath: join(homedir(), '.claude', 'logs', 'mr-history.json')
  })
  ipcMain.handle('mr:history', (_event, opts) => mrHistory.get({ fresh: !!opts?.fresh }))
  // #422: whether the last Open list read every project, and if not which failed and why.
  ipcMain.handle('mr:listStatus', () => prFetch)
  // One merged (or refused) PR as the usual detail view, read-only: never mergeable from here.
  ipcMain.handle('mr:historyDetail', async (_event, url) => {
    const repo = repoFromPrUrl(url)
    if (!repo) throw new Error('not a PR url')
    const { stdout } = await execFileAsync('gh', ['pr', 'view', url, '--json', 'number,title,url,body,files,baseRefName,headRefName,mergeable,statusCheckRollup,state,mergedAt'])
    const raw = { ...JSON.parse(stdout), repo }
    const [pr] = await listPipelinePrs(async () => [raw], { canMerge: () => false, uiPathsFor: (r) => readUiPaths(r) })
    return { ...pr, readOnly: true, state: raw.state, mergedAt: raw.mergedAt || null }
  })

  ipcMain.handle('mr:autoMergeReport', async () => {
    try {
      return (await getAutoMergeShadow()).last_report || null
    } catch {
      return null
    }
  })
  const getRebaseStatus = async () => {
    const res = await fetch(MR_WEBHOOK_URL.replace(/\/approve$/, '/rebase-status'), { signal: AbortSignal.timeout(3000) })
    return res.ok ? res.json() : {}
  }
  // Safety net for stacked PRs whose parent merged without the post-merge move (stack_retarget.js). Reads the PR list
  // already in memory; asks GitHub only about an orphaned PR, at most every 5 minutes each.
  const stackRetarget = createStackRetarget({
    gh: async (args) => (await execFileAsync('gh', args)).stdout,
    onMoved: (moved) => {
      for (const m of moved) {
        console.error(`[stack-retarget] moved PR #${m.number} (${m.repo}) onto main: its parent #${m.parent} had merged`)
        githubChanged(`github:${m.repo}`)
      }
      mainWindow?.webContents.send('mr:refresh')
    }
  })
  // MARVIN_MR_FIXTURE=<file.json> (gh pr list JSON) shows a fixed PR list instead of GitHub's: used to screenshot card
  // states no open PR happens to be in (e.g. "Too vague: needs options") for the owner's image rule.
  const fixturePrs = process.env.MARVIN_MR_FIXTURE ? async () => JSON.parse(readFileSync(process.env.MARVIN_MR_FIXTURE, 'utf8')) : null
  // Overlapping callers share one build of the list (2026-10-21: three ran at once after one Decisions submit, the
  // longest 43 s). A caller after a local write or a change ping gets a new build, from memory, never an older answer.
  const remembered = (kind) => githubState.peek(kind)
  const keysFromBoards = (pick) => async (repos) => {
    const want = new Set(repos)
    const keys = new Set()
    for (const { repo, value } of remembered('board')) if (want.has(repo)) for (const k of pick(repo, value?.issues || [])) keys.add(k)
    return keys
  }
  async function pipelineCardFromMemory(url) {
    const prs = remembered('prs').flatMap(({ repo, value }) => (Array.isArray(value) ? value.map((p) => ({ ...p, repo, listedAt: githubState.fetchedAt('prs', repo) })) : []))
    if (!prs.some((p) => p.url === url)) return null
    const rework = remembered('rework')[0]?.value
    const cards = await listPipelinePrs(async () => prs, {
      canMerge: (repo) => canMergeFromDashboard(repo, readMergeableRepos()),
      sentBackTickets: keysFromBoards(sentBackKeys),
      closedTickets: keysFromBoards((repo, issues) => issues.filter((i) => i.state === 'CLOSED').map((i) => `${repo}#${i.number}`)),
      reworkStatus: rework ? async () => rework : null,
      rebaseStatus: getRebaseStatus,
      autoMergeShadow: getAutoMergeShadow,
      uiPathsFor: (repo) => readUiPaths(repo)
    })
    return cards.find((p) => p.url === url) || null
  }
  const mrList = coalesce(
    () => listPipelinePrs(fixturePrs || listOpenPrs, { canMerge: (repo) => canMergeFromDashboard(repo, readMergeableRepos()), sentBackTickets, reworkStatus: reworkFromMemory, rebaseStatus: getRebaseStatus, closedTickets, autoMergeShadow: getAutoMergeShadow, uiPathsFor: (repo) => readUiPaths(repo) }),
    () => `${githubState.localSeq()}:${githubState._genOf(null)}`
  )
  ipcMain.handle('mr:list', () => {
    if (!fixturePrs) listOpenPrs().then((prs) => stackRetarget.check(prs)).catch(() => {})
    return mrList()
  })

  // Local-first actions (CONTEXT.md "Dashboard actions render their true result locally at once, and confirm in the
  // background"): each action applies GitHub's answer to its own write to memory, asks GitHub about that one PR or
  // ticket once in the background (a conditional request), and says so if GitHub disagrees. See mr_actions.js.
  const notify = (channel, payload) => {
    mainWindow?.webContents.send(channel, payload)
    if (channel === 'mr:corrected') mainWindow?.webContents.send('mr:refresh') // redraw from memory, now GitHub's version
  }
  const localFirst = createLocalFirst({ state: githubState, readIssue: createIssueReader(), onCorrected: (c) => notify('mr:corrected', c) })
  const mrActions = createMrActions({
    state: githubState,
    exec: execFileAsync,
    localFirst,
    listOpenPrs: () => listOpenPrs(),
    // The PR as it now stands, built from memory only: the answer is what GitHub just returned, and anything else a
    // repo needs re-reading for is the background's job, never the click's (a re-read here cost 1.3 s in the sandbox).
    card: (url) => pipelineCardFromMemory(url),
    headCheck: createRepoHeadCheck(),
    notify
  })

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
  // PR description images for the detail view's gallery: fetched here with the shared GitHub credential (private repos),
  // capped and cached, and handed to the renderer as data: URLs, which its CSP allows. The token never reaches the page.
  const prImages = createImageLoader({ cacheDir: prMediaDir() })
  ipcMain.handle('mr:image', (_event, url, kind) => prImages.load(String(url || ''), kind || null))

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
  ipcMain.handle('mr:approve', async (_event, { number, url, head = null }) => {
    // Checked here, not just greyed out in the UI, so a stale screen can't skip it. Sent-back PRs are marked the same way
    // the list marks them, or a newer PR waits forever on one that can't merge (marvin #209). A refusal is recorded (#215).
    // P5: the order check runs on the remembered list after one conditional check of this repo's open PRs (heads,
    // bases), not a fresh re-list of all 13 repos (10.4 s for PR #569). Stale re-reads that one repo.
    await guardApprove(url, {
      assertMergeable,
      loadPrs: async () => prsForOrderCheck(await mrActions.approvePrs(url), sentBackTickets),
      record: recordRefusal
    })
    if (!mergeOps.start(url, Date.now(), head)) return { merged: false, cancelled: true, alreadyMerging: true }
    pushMergeOp(url, mergeOps.get(url))
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
          pushMergeOp(url, { state: 'idle' })
          return { merged: false, cancelled: true }
        }
      }
      // marvin#568: the webhook streams each stage as it happens; each one is folded into the op and pushed.
      const result = await approveMrStream(url, MR_WEBHOOK_URL, { onEvent: (event) => pushMergeOp(url, mergeOps.event(url, event)) })
      if (result?.interrupted) {
        pushMergeOp(url, mergeOps.interrupt(url))
        return { ...result, cancelled: false }
      }
      pushMergeOp(url, mergeOps.finish(url, result))
      // The list must not keep showing a PR that just merged: it leaves at once, and GitHub confirms in the background.
      if (result?.merged) mrActions.merged(url)
      else mrActions.reengaged(url)
      clearReworkCache()
      return { ...result, cancelled: false }
    } catch (err) {
      pushMergeOp(url, mergeOps.fail(url, err.message))
      throw err
    }
  })

  // The one read a card makes when it mounts (a merge already running, or how the last one ended); after that,
  // changes arrive as 'mr:mergeEvent' pushes.
  ipcMain.handle('mr:mergeState', (_event, url, head = null) => mergeOps.get(url, Date.now(), head))

  // The owner's answers to a Decisions section, on a PR or a ticket (2026-10-09): written into the description, then
  // recorded as a comment. See decisions_submit.js.
  // Returns as soon as GitHub accepted the edit, with the PR card as it now stands (Approve unlocks from it); the record
  // comment follows as 'decisions:recorded'.
  ipcMain.handle('decisions:submit', (_event, { repo, number, answers }) => mrActions.submitDecisions({ repo, number, answers }))

  // "Too vague: needs options": ask the author to restate the questions as a Decisions section.
  ipcMain.handle('mr:sendBackForOptions', async (_event, { url, ticketNumber, reasons }) => {
    assertMergeable(url)
    const result = await sendBackForOptions({ prUrl: url, ticketNumber, reasons }, {
      exec: execFileAsync,
      deny: (payload) => denyMr(payload, MR_DENY_WEBHOOK_URL, postJson)
    })
    if (result.sentBack) mrActions.denied({ url, ticketNumber, action: 'feedback' })
    return result
  })

  // The way out of a wrongly shown "sent back": see clearSentBackLabel (refuses while a rework is running).
  ipcMain.handle('mr:clearSentBack', async (_event, url) => {
    assertMergeable(url)
    const result = await clearSentBackLabel(url, execFileAsync)
    if (result.cleared) mrActions.cleared({ url, ticket: result.ticket })
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
    mrActions.denied({ url, ticketNumber, action })
    return { done: true, cancelled: false }
  })
}

// PR recordings (screen recordings in PR descriptions) are cached by the main process and streamed to the PR detail's
// <video> players from here, with byte ranges so they can seek. Only ids of files already in the cache are served.
const prMediaDir = () => join(app.getPath('userData'), 'pr-image-cache')
protocol.registerSchemesAsPrivileged([{ scheme: 'prmedia', privileges: { standard: true, secure: true, stream: true, supportFetchAPI: true } }])

app.whenReady().then(() => {
  protocol.handle('prmedia', (request) => {
    const found = mediaFileFor(prMediaDir(), new URL(request.url).pathname.replace(/^\/+/, ''))
    if (!found) return new Response('not found', { status: 404 })
    return net.fetch(pathToFileURL(found.file).toString(), { headers: request.headers })
  })
  installDevSiteCors(session.defaultSession)   // previews need the dev site's web fonts (see dev_site_cors.js)
  registerMetricsHandlers()
  registerMrReviewHandlers()
  registerDispatchHandlers()
  registerHealthHandlers()
  registerSessionHandlers()
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
  // The support cache (ADR 0073): written by support.py after every sync, so the tab and IT button refresh the moment it does.
  ensureSupportDir()
  triggerHub.watchFiles('support', [{ dir: SUPPORT_DIR, match: (n) => n === 'state.json' }])
  // Notices (ADR 0073 amendment): only a change seen while the app runs; the first read is the baseline.
  let supportSeen = readSupportState()
  triggerHub.onTrigger((t) => {
    if (t.topic !== 'support') return
    const next = readSupportState()
    const notices = supportNotices(supportSeen, next, instance.support().role)
    supportSeen = next
    if (!Notification.isSupported()) return
    for (const n of notices) {
      const note = new Notification({ title: n.title, body: n.body })
      note.on('click', () => {
        mainWindow?.show()
        mainWindow?.webContents.send('support:focus', { repo: n.repo, number: n.number })
      })
      note.show()
    }
  })
  if (supportWatcher(instance.support().role) === 'app') {
    execFileAsync('gh', ['auth', 'token'])
      .then(({ stdout }) => String(stdout).trim())
      .catch(() => '')
      .then((token) => startAppSupportWatch({ repos: () => instance.support().repos, token, startChangeWatch, createGithubProbe }))
  }
  triggerHub.watchFiles('agents', [{ dir: JOBS_DIR, match: (n) => n.endsWith('.json') && !n.startsWith('.') }])
  // Project goals: a profile edit re-reads them once. Registered before the renderer forward so its re-read is fresh.
  triggerHub.watchFiles('goals', [{ dir: PROFILES_DIR, match: (n) => n.endsWith('.json') }])
  triggerHub.onTrigger((t) => t.topic === 'goals' && (goalsCache = null))
  triggerHub.onTrigger((t) => mainWindow?.webContents.send('trigger', t))

  // External pings (webhook-server): bare = the legacy "MR list changed"; with topics = what changed.
  // Port already taken (another dashboard running) = one log line, not a crash (#384).
  startPrCheckWatch()
  startRefreshServer((payload = {}) => {
    const topics = Array.isArray(payload.topics) ? payload.topics : ['mr']
    for (const topic of topics) {
      if (topic === 'mr') {
        githubChanged(payload.source)
        mainWindow?.webContents.send('mr:refresh')
        checkMergedElsewhere(repoOfSource(payload.source))
      } else if (topic === 'merge') {
        // A merge's stage event from the webhook on this Mac (marvin#568): local state only, never a GitHub read.
        const m = payload.merge
        if (m && typeof m.url === 'string' && m.url.startsWith('https://github.com/')) pushMergeOp(m.url, mergeOps.event(m.url, m.event))
      } else triggerHub.emit(topic, payload.source || 'ping')
    }
  }, { port: DASHBOARD_REFRESH_PORT, host: '127.0.0.1' })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
