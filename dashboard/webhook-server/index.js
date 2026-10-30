import { readFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { createServer } from 'http'
import { mergePr, baselineFailsOnMain, mergesAhead, execWithGroupTimeout, runDiskFirstAid } from './merge.js'
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
import { startChangeWatch, createGithubProbe } from './gh_watch.js'
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
    // marvin#568: each stage is pushed as it happens -- on this response when the dashboard asks for a stream, and to
    // an open dashboard on this Mac through the refresh port (a merge started from the phone or the other Mac shows
    // too). Logged to dashboard-webhook.log, and recorded in flight so a restart reports it as interrupted.
    const prUrl = typeof payload?.pr_url === 'string' && payload.pr_url.startsWith('https://github.com/') ? payload.pr_url : null
    const reply = approveResponder(res, { streaming: !!prUrl && wantsStream(req.headers.accept) })
    // marvin#766: a PR this process is already merging is not started again (a retry after a dropped stream).
    if (prUrl && !mergeLatch.take(prUrl)) {
      reply.result(409, alreadyMergingBody(machineId))
      return
    }
    try {
      const tracker = prUrl ? createMergeTracker({
        url: prUrl,
        repo: repoOfPr(prUrl),
        machineId,
        inflight,
        measure: () => machineLoad(),
        estimate: (repo, gated) => estimateMergeMs(repo, gated),
        record: recordMergeDuration,
        emit: (event) => {
          reply.event(event)
          forwardRefreshPing(DASHBOARD_REFRESH_URL, (url) => postJson(url, { topics: ['merge'], source: 'merge', merge: { url: prUrl, event } }))
        }
      }) : null
      tracker?.start(mergesAhead(prUrl))
      try {
        // mergePr() returning normally covers both a real merge (merged:
        // true) and G-Eskayo/marvin#91's merge-time gate routing the ticket
        // to re-engagement instead (merged: false, reengaged: true) -- the
        // latter is an expected outcome, not a server error, so it gets a
        // 200 with the real reason attached rather than a bare 500.
        // P5: the preflight's seven reads of this PR share one (pr_snapshot.js); merge.js and its checks are unchanged.
        const result = await mergePr(payload.pr_url, snapshotExec(payload.pr_url, execWithGroupTimeout), undefined, undefined, undefined, undefined, undefined, undefined, {
          baselineFails: (names) => baselineFailsOnMain(names),
          progress: tracker ? tracker.progress : undefined,
          loadNow: () => ({ ...machineLoad(), id: machineId }),
          // A nearly full disk gets the cleanup sweep's rebuildable trims once before the gate refuses (2026-10-28).
          diskFirstAid: () => runDiskFirstAid()
        })
        tracker?.finish(result)
        if (result?.merged) appendMerge(payload.pr_url, payload.by === 'auto' ? 'auto' : 'you')
        else if (result?.reengaged) console.error(approveErrorLine(payload.pr_url, { error: `${result.code || 'SENT_BACK'} at ${result.stage || 'gate'}: ${String(result.reason || 'sent back for rework').split('\n')[0].slice(0, 200)}` }))
        reply.result(200, result)
      } catch (err) {
        // Structured: code, stage, retryable, action, remediation -- so the dashboard can say
        // what broke and the pipeline can act on it (see failure.js).
        const { status, body } = failureResponse(err)
        tracker?.fail(body)
        console.error(approveErrorLine(payload.pr_url, body))
        await recordApproveError(payload.pr_url, body)
        appendError({ source: 'webhook:approve', message: `Approve refused for ${payload.pr_url}`, raw: body.error })
        reply.result(status, body)
      }
    } finally {
      if (prUrl) mergeLatch.release(prUrl)
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

const rebuildCheck = createRebuildCheckTrigger()

// marvin#568: which Mac runs the merges (shown on the card), and the in-flight record a restart reads.
const machineId = resolveDeviceId()
const inflight = createInflightStore()
const mergeLatch = createMergeLatch()
const repoOfPr = (url) => (String(url).match(/github\.com\/([^/]+\/[^/]+)\/pull\//) || [])[1] || null

server.listen(PORT, () => {
  console.log(`MR-approval webhook listening on http://localhost:${PORT}/approve`)
  console.log(`GitHub credential source: ${ghTokenSource}`)

  // A merge that was running when the last process died is over: say so now (log + one event to an open dashboard
  // here), instead of its card reading "Merging…" until the 45-minute limit. Resuming is not attempted: the gate's
  // scratch worktree died with the process, and Approve again is safe (the gate starts from GitHub's state).
  for (const { url, event } of takeInterruptedMerges()) {
    forwardRefreshPing(DASHBOARD_REFRESH_URL, (u) => postJson(u, { topics: ['merge'], source: 'merge', merge: { url, event } }))
  }

  // marvin#762: this Mac can merge again. Saved approvals (on this Mac's dashboard, and on the other Mac's, which
  // could not reach this one) are retried on this, not on a timer.
  announceMergeHost({
    machineId,
    localRefreshUrl: DASHBOARD_REFRESH_URL,
    peers: peerHosts(),
    post: (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(5000) })
  }).then(({ told, of }) => console.log(`[merge-host] announced this Mac can merge: ${told} of ${of} reached`))

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
      forwardRefreshPing(DASHBOARD_REFRESH_URL, (url) => postJson(url, { topics: ['activity', 'mr'], source: `github:${repo}` }))
      forwardRefreshPing(MOBILE_REFRESH_URL, postJson)
    }
  })
})
