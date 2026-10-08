import { approveMr, denyMr } from '../electron/main/mr_review.js'
import { guardApprove } from '../electron/main/approve_guard.js'
import { repoFromPrUrl, canMergeFromDashboard } from '../electron/main/mr_repos.js'
import { readMergeableRepos } from '../electron/main/profiles.js'
import { recordRefusal } from '../webhook-server/refusal_log.js'
import { promisify } from 'util'
import { execFile } from 'child_process'

const execFileAsync = promisify(execFile)

// Helper to parse JSON body from request
async function readJsonBody(req) {
  let body = ''
  for await (const chunk of req) {
    body += chunk.toString()
  }
  return JSON.parse(body)
}

// Minimal assertMergeable for the mobile backend: checks if repo can be merged from dashboard
function assertMergeable(url) {
  const repo = repoFromPrUrl(url)
  if (!repo || !canMergeFromDashboard(repo, readMergeableRepos())) {
    const error = new Error(`Merging ${repo || 'this PR'} from the dashboard isn't set up: its project profile has not opted in (merge_from_dashboard).`)
    error.code = 'NO_MERGE_PROFILE'
    throw error
  }
}

// Fetch wrapper compatible with approveMr/denyMr expectations
function postJson(url, data) {
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export function createMrActionsApiRouter(opts = {}) {
  const webhookUrl = opts.webhookUrl || process.env.MARVIN_MR_WEBHOOK_URL || 'http://localhost:7878/approve'
  const denyWebhookUrl = opts.denyWebhookUrl || process.env.MARVIN_MR_DENY_WEBHOOK_URL || 'http://localhost:7878/deny'
  const exec = opts.exec || execFileAsync

  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`)
    const pathname = url.pathname

    try {
      // POST /mr/approve
      if (req.method === 'POST' && pathname === '/mr/approve') {
        let payload
        try {
          payload = await readJsonBody(req)
        } catch {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Invalid JSON' })
          )
          return true
        }

        const { url: prUrl, number, confirmed } = payload

        if (confirmed !== true) {
          res.writeHead(403, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Action requires Face ID confirmation (confirmed: true)' })
          )
          return true
        }

        if (!prUrl || !number) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing required fields: url, number' })
          )
          return true
        }

        try {
          // Guards: check if repo can merge, load PRs, check merge order
          await guardApprove(prUrl, {
            assertMergeable,
            loadPrs: async () => {
              const { stdout } = await exec('gh', ['pr', 'list', '--repo', 'G-Eskayo/marvin', '--state', 'open', '--json', 'number,title,url,body,files,baseRefName,headRefName,mergeable,statusCheckRollup', '--limit', '200'])
              return JSON.parse(stdout)
            },
            record: recordRefusal
          })

          // Approve the PR via webhook
          const result = await approveMr(prUrl, webhookUrl, postJson)
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: { ...result, cancelled: false } })
          )
        } catch (err) {
          // Check if this is a structured error from guardApprove
          if (err.payload) {
            res.writeHead(400, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: err.message, ...err.payload })
            )
          } else if (err.code) {
            // A refusal code
            res.writeHead(400, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: err.message, code: err.code })
            )
          } else {
            res.writeHead(500, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: err.message })
            )
          }
        }
        return true
      }

      // POST /mr/deny
      if (req.method === 'POST' && pathname === '/mr/deny') {
        let payload
        try {
          payload = await readJsonBody(req)
        } catch {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Invalid JSON' })
          )
          return true
        }

        const { url: prUrl, number, ticketNumber, action, reasons, comment, confirmed } = payload

        if (confirmed !== true) {
          res.writeHead(403, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Action requires Face ID confirmation (confirmed: true)' })
          )
          return true
        }

        if (!prUrl || !number || !action) {
          res.writeHead(400, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: false, error: 'Missing required fields: url, number, action' })
          )
          return true
        }

        try {
          // Check that the repo can merge (same gate as approve)
          assertMergeable(prUrl)

          // Deny the PR via webhook
          await denyMr(
            { prUrl, ticketNumber, action, reasons, comment },
            denyWebhookUrl,
            postJson
          )
          res.writeHead(200, { 'Content-Type': 'application/json' }).end(
            JSON.stringify({ ok: true, data: { done: true } })
          )
        } catch (err) {
          if (err.code) {
            res.writeHead(400, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: err.message, code: err.code })
            )
          } else {
            res.writeHead(500, { 'Content-Type': 'application/json' }).end(
              JSON.stringify({ ok: false, error: err.message })
            )
          }
        }
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
