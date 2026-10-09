import { readFileSync } from 'fs'
import os from 'os'
import path from 'path'
import { createServer } from 'http'
import { mergePr, baselineFailsOnMain } from './merge.js'
import { sendFeedback, dropEntirely } from './deny.js'
import { forwardRefreshPing } from './refresh_relay.js'
import { loadGhToken } from './gh_auth.js'
import { useGhGate } from '../electron/main/path.js'
import { failureResponse } from './failure.js'
import { timeRequest } from '../electron/main/timing.js'
import { recordApproveError, approveErrorLine } from './refusal_log.js'
import { readRebaseStatus } from './rebase_status.js'
import { readLiveSessions } from './sessions.js'
import { startChangeWatch, createGithubProbe } from './gh_watch.js'
import { readRegistry } from '../electron/main/boards.js'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { createPortfolio } from '../electron/main/portfolio.js'
import { handlePortfolioRequest } from '../electron/main/portfolio_remote.js'
import { resolveServiceDefaults } from '../electron/main/device_identity.js'

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

  if (req.method === 'GET' && req.url === '/rebase-status') {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(readRebaseStatus()))
    return
  }

  if (req.method === 'GET' && req.url === '/sessions') {
    res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ sessions: readLiveSessions() }))
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
    try {
      // mergePr() returning normally covers both a real merge (merged:
      // true) and G-Eskayo/marvin#91's merge-time gate routing the ticket
      // to re-engagement instead (merged: false, reengaged: true) -- the
      // latter is an expected outcome, not a server error, so it gets a
      // 200 with the real reason attached rather than a bare 500.
      const result = await mergePr(payload.pr_url, undefined, undefined, undefined, undefined, undefined, undefined, undefined, { baselineFails: (names) => baselineFailsOnMain(names) })
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(result))
    } catch (err) {
      // Structured: code, stage, retryable, action, remediation -- so the dashboard can say
      // what broke and the pipeline can act on it (see failure.js).
      const { status, body } = failureResponse(err)
      console.error(approveErrorLine(payload.pr_url, body))
      await recordApproveError(payload.pr_url, body)
      res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(body))
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
    res.writeHead(500, { 'Content-Type': 'application/json' }).end(
      JSON.stringify({ done: false, error: String(err.message || err) })
    )
  }
})

server.listen(PORT, () => {
  console.log(`MR-approval webhook listening on http://localhost:${PORT}/approve`)
  console.log(`GitHub credential source: ${ghTokenSource}`)

  // Trigger source for GitHub-side changes to any board repo: tell an open dashboard on this
  // machine what changed the moment it does (best-effort, like /mr-ready).
  startChangeWatch({
    getRepos: () => readRegistry().map((b) => b.repo),
    probe: createGithubProbe(),
    ping: (repo) => {
      console.log(`[gh-watch] change detected on ${repo} at ${new Date().toISOString()}`)
      forwardRefreshPing(DASHBOARD_REFRESH_URL, (url) => postJson(url, { topics: ['activity', 'mr'], source: `github:${repo}` }))
      forwardRefreshPing(MOBILE_REFRESH_URL, postJson)
    }
  })
})
