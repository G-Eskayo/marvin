import { readFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { createServer } from 'http'
import { mergePr, baselineFailsOnMain, mergesAhead, execWithGroupTimeout, runDiskFirstAid, memoryGuardCheck, withMergeMark, forgetQueuedMerge, readMergeReady, sweepGateClones, repoJobsDone, triggerTicketPipeline } from './merge.js'
import { createMergeQueue, createQueueStore } from './merge_queue.js'
import { createUnbuiltCache, createFixTicketsCache, createQueueLoader, createBaseLookup, createFollowUpRequester, readMainHealth, readRepairFailures } from './merge_facts.js'
import { pendingCheckHeads } from '../electron/main/mr_repos.js'
import { snapshotExec } from './pr_snapshot.js'
import { createMergeTracker, createInflightStore, takeInterruptedMerges, recordMergeDuration, estimateMergeMs, machineLoad, approveResponder, wantsStream, createMergeLatch, alreadyMergingBody } from './merge_progress.js'
import { resolveDeviceId, peerHosts } from '../electron/main/device_identity.js'
import { sendFeedback, dropEntirely } from './deny.js'
import { forwardRefreshPing } from './refresh_relay.js'
import { announceMergeHost, relayMergeHostUp } from './merge_host_announce.js'
import { loadGhToken } from './gh_auth.js'
import { useGhGate } from '../electron/main/path.js'
import { failureResponse } from './failure.js'
import { timeRequest } from '../electron/main/timing.js'
import { recordApproveError, approveErrorLine } from './refusal_log.js'
import { appendMerge, readMergeHistory } from './merge_history.js'
import { appendError } from '../electron/main/error_log.js'
import { readRebaseStatus } from './rebase_status.js'
import { readLiveSessions } from './sessions.js'
import { listHelpers } from './chat_helpers.js'
import { startChangeWatch, createGithubProbe, startCheckWatch, createCheckProbe } from './gh_watch.js'
import { readRegistry } from '../electron/main/boards.js'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { createPortfolio } from '../electron/main/portfolio.js'
import { handlePortfolioRequest } from '../electron/main/portfolio_remote.js'
import { resolveServiceDefaults } from '../electron/main/device_identity.js'
import { createRebuildCheckTrigger } from './rebuild_check.js'
import { supportRepos, createSupportSync } from './support_sync.js'
import { handleSafetyRequest, SAFETY_MAX_BODY } from './safety_labels.js'

// Authenticate gh/git children from the pipeline's shared credential file (see gh_auth.js).
const ghTokenSource = loadGhToken()
// ...and through the GitHub gate (path.js), so dashboard clicks share the cooldown with every other caller.
useGhGate()

const PORT = process.env.PORT || 7878

// ADR 0038: this is the dev host, so the Portfolio tab's backend runs here and other machines' dashboards call it.
const portfolio = createPortfolio({ exec: promisify(execFile) })
const PORTFOLIO_MAX_BODY = 1024 * 1024   // the largest argument is a project spec, which portfolio.js caps at 200 KB

function readBody(req, limit) {
  return new Promise((resolve, reject) => {
    let body = ''
    req.on('data', (chunk) => {
      body += chunk
      if (body.length > limit) {
        reject(new Error('Body too large'))
        req.destroy()
      }
    })
    req.on('end', () => resolve(body))
    req.on('error', reject)
  })
}
// The Electron app's own tiny local server (electron/main/index.js),
// separate from this process -- see refresh_relay.js for why the hop
// exists at all.
const DASHBOARD_REFRESH_URL = process.env.MARVIN_DASHBOARD_REFRESH_URL || 'http://localhost:7879/refresh'

// The mobile backend's refresh listener (best-effort forward; mobile backend may not be running).
// Resolves to localhost when running on the primary host, or the primary host's Tailscale name otherwise.
const serviceDefaults = resolveServiceDefaults()
const MOBILE_REFRESH_PORT = process.env.MARVIN_MOBILE_REFRESH_PORT || '7881'
const MOBILE_REFRESH_URL = process.env.MARVIN_MOBILE_REFRESH_URL || `http://${serviceDefaults.host}:${MOBILE_REFRESH_PORT}/refresh`

function postJson(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let body = ''
    req.on('data', (chunk) => {
      body += chunk
    })
    req.on('end', () => {
      try {
        resolve(JSON.parse(body))
      } catch {
        reject(new Error('Invalid JSON body'))
      }
    })
  })
}

const server = createServer(async (req, res) => {
  timeRequest(req, res) // every route timed into ~/.claude/logs/dashboard-timing.jsonl (#236)
  // mr_raiser.py hits this the moment a PR is raised (any machine) so an
  // already-open dashboard on THIS machine refreshes immediately instead
  // of waiting on its own fallback poll. Responds before the forward
  // resolves -- the caller (an autonomous pipeline run) shouldn't wait on
  // whether a dashboard happens to be open here.
  if (req.method === 'POST' && req.url === '/mr-ready') {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: true }))
    forwardRefreshPing(DASHBOARD_REFRESH_URL, postJson)
    forwardRefreshPing(MOBILE_REFRESH_URL, postJson)
    return
  }

  // The safety monitor's shared calibration (safety_labels.js): other Macs deliver review answers, read the tau map.
  if (req.url === '/safety/label' || req.url === '/safety/taus') {
    let body = ''
    if (req.method === 'POST') {
      try {
        body = await readBody(req, SAFETY_MAX_BODY)
      } catch (err) {
        res.writeHead(413, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: err.message }))
        return
      }
    }
    const calibrateScript = path.join(os.homedir(), '.agents', 'skills', 'safety-monitor', 'scripts', 'calibrate.py')
    const python = path.join(os.homedir(), '.agents', 'venv', 'bin', 'python')
    const run = async (args) => (await promisify(execFile)(python, [calibrateScript, ...args], { timeout: 30_000 })).stdout
    const { status, json } = await handleSafetyRequest({ method: req.method, url: req.url, body }, run)
    res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(json))
    return
  }

  if (req.method === 'POST' && req.url.startsWith('/portfolio/')) {
    let body
    try {
      body = await readBody(req, PORTFOLIO_MAX_BODY)
    } catch (err) {
      res.writeHead(413, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ok: false, error: err.message }))
      return
    }
    const { status, json } = await handlePortfolioRequest(portfolio, req.url, body)
    res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(json))
    return
  }

  // The latest post-merge rebase result per open PR (#225), for MR Review on any machine.
  // Auto-merge's shadow state (ADR 0064, #341): read-only, for MR Review on either Mac.
  if (req.method === 'GET' && req.url === '/auto-merge-shadow') {
    let body = '{}'
    try {
      body = readFileSync(path.join(os.homedir(), '.claude', 'logs', 'auto-merge-shadow.json'), 'utf-8')
      JSON.parse(body)
    } catch {
      body = '{}'
    }
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(body)
    return
  }

  // MR Review's Merged view (#419): what this server merged and every Approve it refused, for either Mac.
  if (req.method === 'GET' && req.url === '/merge-history') {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(readMergeHistory()))
    return
  }

  // marvin#231: the merge queue, for MR Review on either Mac and the phone: what is queued per repo (in approval order),
  // what left it failing, what runs now, and the facts the order is worked out from that only this Mac has.
  if (req.method === 'GET' && req.url === '/merge-queue') {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({
      repos: mergeQueue.snapshot(),
      facts: { unbuilt: [...unbuiltCache.get()], unbuiltAt: unbuiltCache.at(), repairFailed: readRepairFailures(), health: readMainHealth(), tickets: fixTickets.get() },
      machine: machineId
    }))
    return
  }

  if (req.method === 'GET' && req.url === '/rebase-status') {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(readRebaseStatus()))
    return
  }

  if (req.method === 'GET' && req.url === '/sessions') {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ sessions: readLiveSessions() }))
    return
  }

  // Chat helpers on this Mac (#612), for the other Mac's Activity tab. Read-only, like /sessions.
  if (req.method === 'GET' && req.url === '/helpers') {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ helpers: listHelpers() }))
    return
  }

  // marvin#762: another Mac's webhook just started, so it can merge again: tell the dashboard here, which retries the
  // approvals it saved while no Mac could merge. Only ever triggers that retry; the body names the machine, nothing more.
  if (req.method === 'POST' && req.url === '/merge-host-up') {
    let body = null
    try { body = await readJsonBody(req) } catch { /* the trigger is the request itself */ }
    await relayMergeHostUp(body, { localRefreshUrl: DASHBOARD_REFRESH_URL, post: postJson })
    res.writeHead(200, { 'Content-Type': 'application/json' }).end('{"ok":true}')
    return
  }

  // marvin#940 part 4: a dashboard asks whether this Mac is fit to merge in the Mini's place (awake, on power, at home,
  // idle), and tells the Mini to drop its queued copy before another Mac merges it. Read-only and one queue file.
  if (req.method === 'GET' && req.url.split('?')[0] === '/merge-ready') {
    const repo = new URL(req.url, 'http://localhost').searchParams.get('repo') || ''
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(await readMergeReady(repo)))
    return
  }
  if (req.method === 'POST' && req.url === '/merge-forget') {
    let body = null
    try { body = await readJsonBody(req) } catch { /* answered below */ }
    const prUrl = typeof body?.pr_url === 'string' && body.pr_url.startsWith('https://github.com/') ? body.pr_url : null
    res.writeHead(prUrl ? 200 : 400, { 'Content-Type': 'application/json' }).end(JSON.stringify({ forgotten: prUrl ? await forgetQueuedMerge(prUrl) : false }))
    return
  }

  if (req.method !== 'POST' || (req.url !== '/approve' && req.url !== '/deny')) {
    res.writeHead(404).end()
    return
  }

  const isApprove = req.url === '/approve'
  const invalidBodyKey = isApprove ? 'merged' : 'done'

  let payload
  try {
    payload = await readJsonBody(req)
  } catch (err) {
    res.writeHead(400, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ [invalidBodyKey]: false, error: err.message })
    )
    return
  }

  if (isApprove) {
    const prUrl = typeof payload?.pr_url === 'string' && payload.pr_url.startsWith('https://github.com/') ? payload.pr_url : null
    const reply = approveResponder(res, { streaming: !!prUrl && wantsStream(req.headers.accept) })
    // Not a PR url: refused at once, as before (mergePr's own check says why).
    if (!prUrl) {
      const { status, body } = await runMerge(payload?.pr_url, { by: payload?.by, reply })
      reply.result(status, body)
      return
    }
    // marvin#766: a PR this process is already merging is not started again (a retry after a dropped stream).
    if (mergeQueue.isRunning(prUrl)) {
      reply.result(409, alreadyMergingBody(machineId))
      return
    }
    // marvin#231: Approve queues the merge. The queue merges in the order it works out (stacked PRs base first, only the
    // fix while main is red), one at a time per repo. When this PR is next it runs now and this response follows it,
    // as before; otherwise the answer is its place and what it waits for, and it merges by itself when its turn comes.
    // marvin#940: this Approve drops the same PR's copy queued for memory, so the memory queue never runs it twice.
    if (payload.by !== 'memory-queue') await forgetQueuedMerge(prUrl)
    let answered = false
    const attach = {
      url: prUrl,
      reply,
      queued: (entry) => {
        if (answered) return
        answered = true
        reply.result(200, queuedBody(prUrl, entry))
      },
      ran: () => { answered = true }
    }
    try {
      await mergeQueue.approve(repoOfPr(prUrl), prUrl, { by: payload.by === 'auto' ? 'auto' : payload.by === 'memory-queue' ? 'memory-queue' : 'you', attach })
    } finally {
      if (!answered) attach.queued(mergeQueue.view(repoOfPr(prUrl))?.entries?.[prUrl] || null)
      // marvin#940: an approval that waited for memory has run (or is queued) by itself. The dashboards show it waiting;
      // this is their trigger to look again (approval_retry.js concludes it from GitHub's state).
      if (payload?.by === 'memory-queue') announceThisMac('memory-queue run finished')
    }
    return
  }

  // req.url === '/deny'
  const { action, pr_url: prUrl, ticket_number: ticketNumber, reasons, comment } = payload
  if (action !== 'send_feedback' && action !== 'drop') {
    res.writeHead(400, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ done: false, error: `Unknown deny action: ${action}` })
    )
    return
  }

  try {
    if (action === 'send_feedback') {
      await sendFeedback({ prUrl, ticketNumber, reasons, comment })
    } else {
      await dropEntirely({ prUrl, ticketNumber })
    }
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ done: true }))
  } catch (err) {
    appendError({ source: 'webhook:deny', message: `Deny failed for ${prUrl}`, raw: err?.stack || err })
    res.writeHead(500, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ done: false, error: String(err.message || err) })
    )
  }
})

// marvin#762/#940: tell this Mac's dashboard and the other Macs' that this one can merge (or just merged a waiting
// approval): each runs one pass over the approvals it saved. A trigger, never a timer.
function announceThisMac(why) {
  return announceMergeHost({
    machineId,
    localRefreshUrl: DASHBOARD_REFRESH_URL,
    peers: peerHosts(),
    post: (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(5000) })
  }).then(({ told, of }) => console.log(`[merge-host] ${why}: told ${told} of ${of}`)).catch(() => { /* best effort */ })
}

const rebuildCheck = createRebuildCheckTrigger()

// marvin#568: which Mac runs the merges (shown on the card), and the in-flight record a restart reads.
const machineId = resolveDeviceId()
const inflight = createInflightStore()
const mergeLatch = createMergeLatch()
const repoOfPr = (url) => (String(url).match(/github\.com\/([^/]+\/[^/]+)\/pull\//) || [])[1] || null

// One merge through the existing gate, exactly as an Approve ran it before the queue (marvin#568 stages, #845 memory,
// #940 the merge mark): { status, body }. `reply` is the Approve still waiting for its answer, when there is one; a
// merge the queue starts by itself is followed through the refresh pings instead (this Mac's dashboard, and the
// other Macs' through their own reads of /merge-queue).
async function runMerge(prUrl, { by = 'you', reply = null } = {}) {
  const valid = typeof prUrl === 'string' && prUrl.startsWith('https://github.com/')
  if (valid && !mergeLatch.take(prUrl)) return { status: 409, body: alreadyMergingBody(machineId) }
  try {
    const tracker = valid ? createMergeTracker({
      url: prUrl,
      repo: repoOfPr(prUrl),
      machineId,
      inflight,
      measure: () => machineLoad(),
      estimate: (repo, gated) => estimateMergeMs(repo, gated),
      record: recordMergeDuration,
      emit: (event) => {
        reply?.event(event)
        forwardRefreshPing(DASHBOARD_REFRESH_URL, (url) => postJson(url, { topics: ['merge'], source: 'merge', merge: { url: prUrl, event } }))
      }
    }) : null
    tracker?.start(mergesAhead(prUrl))
    try {
      // mergePr() returning normally covers both a real merge (merged: true) and G-Eskayo/marvin#91's merge-time gate
      // routing the ticket to re-engagement instead (merged: false, reengaged: true): an expected outcome, a 200.
      // P5: the preflight's seven reads of this PR share one (pr_snapshot.js); merge.js and its checks are unchanged.
      // marvin#940: marked as a merge from here to its end, so new helpers wait and other test runs let it go first;
      // its end kicks the memory guard's queue (a merge ending may let the next queued item start).
      const result = await withMergeMark(() => mergePr(prUrl, snapshotExec(prUrl, execWithGroupTimeout), undefined, undefined, undefined, undefined, undefined, undefined, {
        baselineFails: (names) => baselineFailsOnMain(names),
        progress: tracker ? tracker.progress : undefined,
        loadNow: () => ({ ...machineLoad(), id: machineId }),
        // A nearly full disk gets the cleanup sweep's rebuildable trims once before the gate refuses (2026-10-28).
        diskFirstAid: () => runDiskFirstAid(),
        // marvin#845: no rebase + retest while memory pressure is at warn or critical; this Approve is queued instead.
        memoryCheck: (url) => memoryGuardCheck(url, PORT)
      }))
      tracker?.finish(result)
      if (result?.merged) appendMerge(prUrl, by === 'auto' ? 'auto' : 'you')
      else if (result?.reengaged) console.error(approveErrorLine(prUrl, { error: `${result.code || 'SENT_BACK'} at ${result.stage || 'gate'}: ${String(result.reason || 'sent back for rework').split('\n')[0].slice(0, 200)}` }))
      return { status: 200, body: result }
    } catch (err) {
      // Structured: code, stage, retryable, action, remediation -- so the dashboard can say what broke and the pipeline
      // can act on it (see failure.js). Recorded in the refusal log (#215) and the error log.
      const { status, body } = failureResponse(err)
      tracker?.fail(body)
      console.error(approveErrorLine(prUrl, body))
      await recordApproveError(prUrl, body)
      appendError({ source: 'webhook:approve', message: `Approve refused for ${prUrl}`, raw: body.error })
      return { status, body }
    }
  } finally {
    if (valid) mergeLatch.release(prUrl)
  }
}

// What an Approve that is not run straight away is told: it is in the queue, where, and what it waits for.
function queuedBody(prUrl, entry) {
  return { merged: false, mergeQueued: true, url: prUrl, state: entry?.state || 'queued', position: entry?.position ?? null,
    reason: entry?.reason || 'queued', waitsFor: entry?.waitsFor ?? null }
}

// marvin#231: the queue and what it reads. Answered-but-unbuilt Decisions are re-read on triggers (startup, an Approve,
// a GitHub change on a repo with something queued), never on a timer.
const execAsync = promisify(execFile)
const unbuiltCache = createUnbuiltCache({ exec: execAsync, log: (m) => console.warn(m) })
const requestFollowUp = createFollowUpRequester({ exec: execAsync, log: (m) => console.log(m) })
const fixTickets = createFixTicketsCache({ exec: execAsync, owners: () => [...new Set(readRegistry().map((b) => String(b.repo).split('/')[0]).filter(Boolean))], log: (m) => console.warn(m) })
// Everything MR Review reads from here besides the queue: refreshed together on each trigger.
const refreshFacts = () => Promise.all([unbuiltCache.refresh(), fixTickets.refresh()])
const triggeredResolver = new Map() // url -> head sha the conflict resolver was started for
const mergeQueue = createMergeQueue({
  store: createQueueStore(),
  load: createQueueLoader({ exec: execAsync, unbuilt: () => unbuiltCache.get(), baseOf: createBaseLookup({ exec: execAsync }) }),
  run: async (url, attach) => {
    attach?.ran()
    const { status, body } = await runMerge(url, { by: 'you', reply: attach?.reply || null })
    if (attach) attach.reply.result(status, body)
    return status === 200 ? { result: body } : { body }
  },
  // The merge's after-steps run in the repo's job line (stacked PRs moved onto main, the others conflict-checked):
  // the next decision waits for them, so a stacked PR is seen on main, not as an orphan.
  afterRun: (repo) => repoJobsDone(repo),
  onWaiting: (repo, pr, entry) => {
    if (entry.unbuilt) requestFollowUp(repo, pr.number)
    // A conflict goes to the #230 resolver, which the ticket scan runs (conflict_repair.py): started once per commit.
    if (entry.conflict && !pr.repairFailed && triggeredResolver.get(pr.url) !== pr.headRefOid) {
      triggeredResolver.set(pr.url, pr.headRefOid)
      try { triggerTicketPipeline() } catch { /* the hourly scan gets it */ }
    }
  },
  log: (m) => console.log(m)
})
// The check watch (marvin#555) for queued PRs only: their checks finishing is a trigger. Nothing queued: no requests.
function queuedPendingHeads() {
  const heads = []
  for (const repo of Object.keys(mergeQueue.snapshot())) {
    const view = mergeQueue.view(repo)
    if (!view) continue
    for (const pr of view.prs || []) if (view.entries[pr.url]?.queued) heads.push(...pendingCheckHeads(repo, [pr]))
  }
  return heads
}

server.listen(PORT, () => {
  console.log(`MR-approval webhook listening on http://localhost:${PORT}/approve`)
  console.log(`GitHub credential source: ${ghTokenSource}`)

  // A merge that was running when the last process died is over: say so now (log + one event to an open dashboard
  // here), instead of its card reading "Merging…" until the 45-minute limit. Resuming is not attempted: the gate's
  // scratch worktree died with the process, and Approve again is safe (the gate starts from GitHub's state).
  for (const { url, event } of takeInterruptedMerges()) {
    forwardRefreshPing(DASHBOARD_REFRESH_URL, (u) => postJson(u, { topics: ['merge'], source: 'merge', merge: { url, event } }))
  }
  // marvin#866: ...and that merge's temporary clone (~660 MB) died with it, its finally never ran. Clear any older than
  // 2 h; a merge that has started since this process did is kept (merge.js sweepGateClones).
  sweepGateClones().catch((e) => console.warn(`[merge] startup sweep of gate copies failed: ${e?.message || e}`))

  // marvin#762: this Mac can merge again. Saved approvals (on this Mac's dashboard, and on the other Mac's, which
  // could not reach this one) are retried on this, not on a timer.
  announceThisMac('webhook started')

  // marvin#231: a restart picks the queue up where it was (it is on disk): the facts are read, then each repo with
  // something queued decides again. A merge that was running when the process died is simply run again from GitHub's
  // state (the gate starts from scratch), unless it merged or closed meanwhile (then it leaves the queue).
  refreshFacts().finally(() => mergeQueue.kickAll().catch((e) => console.warn(`[merge-queue] startup: ${e?.message || e}`)))
  startCheckWatch({
    getHeads: () => queuedPendingHeads(),
    probe: createCheckProbe(),
    onChange: (repo) => { mergeQueue.kick(repo).catch(() => {}) }
  })

  // Trigger source for GitHub-side changes to any board repo: tell an open dashboard on this
  // machine what changed the moment it does (best-effort, like /mr-ready).
  // Support repos (ADR 0073) ride the same detector: a change re-syncs the support cache, and on a helper install the
  // helper's MARVIN takes each request that has just been escalated to it. Once now, so the cache exists at startup.
  const supportSync = createSupportSync()
  if (supportRepos().length) supportSync('startup')
  startChangeWatch({
    getRepos: () => [...new Set([...readRegistry().map((b) => b.repo), ...supportRepos()])],
    probe: createGithubProbe(),
    ping: (repo) => {
      if (supportRepos().includes(repo)) {
        console.log(`[gh-watch] support change on ${repo} at ${new Date().toISOString()}`)
        supportSync(repo)
        return
      }
      console.log(`[gh-watch] change detected on ${repo} at ${new Date().toISOString()}`)
      if (rebuildCheck(repo)) console.log(`[rebuild-check] started for ${repo}`) // #443: any merge path updates the app
      // marvin#231: a PR updated, a ticket labelled, main's CI opening or closing its main-red ticket: the queue looks
      // again (answers first, so a just-built PR is seen built).
      refreshFacts().finally(() => mergeQueue.kick(repo).catch(() => {}))
      forwardRefreshPing(DASHBOARD_REFRESH_URL, (url) => postJson(url, { topics: ['activity', 'mr'], source: `github:${repo}` }))
      forwardRefreshPing(MOBILE_REFRESH_URL, postJson)
    }
  })
})
