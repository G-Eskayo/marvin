import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { repoFromPrUrl } from '../electron/main/mr_repos.js'
import { mergePr, assertTargetsBase, assertNotSentBack } from './merge.js'
import { listOpenPrs } from '../electron/main/boards.js'
import { readStages } from './ticket_stages.js'

// Order check: copied from pr_order.js so this webhook module doesn't depend on electron code.
// A PR waits on every OLDER open PR in its repo that shares a changed file.
function waitingOn(prs, pr) {
  if (!Array.isArray(pr.files)) return []
  const mine = new Set(pr.files.map((f) => f.path))
  return prs
    .filter((o) => o.repo === pr.repo && o.number < pr.number && Array.isArray(o.files) && o.mergeable !== 'CONFLICTING' && !o.sentBack && !o.blocked)
    .map((o) => ({ number: o.number, title: o.title, url: o.url, shared: o.files.map((f) => f.path).filter((p) => mine.has(p)).sort() }))
    .filter((o) => o.shared.length)
    .sort((a, b) => a.number - b.number)
}

export const QUEUE_DIR = path.join(homedir(), '.claude', 'logs', 'merge-queue')

// Persistence: one JSON file per repo, formatted as repo-slug (e.g., "G-Eskayo-marvin.json" for G-Eskayo/marvin)
function queueFile(repo, dir = QUEUE_DIR) {
  const slug = repo.replace(/[^a-z0-9]/gi, '-').toLowerCase()
  return path.join(dir, `${slug}.json`)
}

function readQueue(repo, dir = QUEUE_DIR) {
  const file = queueFile(repo, dir)
  if (!existsSync(file)) return []
  try {
    return JSON.parse(readFileSync(file, 'utf-8'))
  } catch {
    return []
  }
}

function writeQueue(repo, entries, dir = QUEUE_DIR) {
  mkdirSync(dir, { recursive: true })
  const file = queueFile(repo, dir)
  writeFileSync(file, JSON.stringify(entries, null, 2))
}

// Returns a canonical number from a PR URL (e.g., 123 from https://github.com/O/R/pull/123)
function prNumberFromUrl(prUrl) {
  const m = String(prUrl).match(/\/pull\/(\d+)/)
  return m ? Number(m[1]) : null
}

// Active drains per repo, one at a time (same shape as inRepoQueue in merge.js)
const activeWrains = new Map()

// Per-repo queue state, keyed by repo URL (e.g., "G-Eskayo/marvin")
const queueState = new Map()

// Track the next poll fallback for a repo (as per "polling stays a backstop" principle)
const pollTimeouts = new Map()

/**
 * Get the current queue status for a repo, suitable for dashboard display.
 * Returns { repo, entries } with each entry enriched with current stage if running.
 */
export function status(repo, dir = QUEUE_DIR) {
  const entries = readQueue(repo, dir)
  // Enrich each entry with its current stage name if it's running
  return {
    repo,
    entries: entries.map(entry => {
      if (entry.status !== 'running') return entry
      const stages = readStages(entry.ticketNumber, undefined, entry.repo)
      const lastStage = stages[stages.length - 1]
      return { ...entry, currentStage: lastStage?.stage || null }
    })
  }
}

/**
 * Enqueue a PR for merge. Returns { queued: true, position } on success,
 * or throws a MergeFailure on hard refusal (targets base, sent back).
 * Idempotent: re-enqueueing the same PR returns its current position.
 */
export async function enqueue(prUrl, exec, dir = QUEUE_DIR) {
  if (!exec) {
    throw new Error('exec is required')
  }

  const repo = repoFromPrUrl(prUrl)
  if (!repo) {
    throw new Error(`Invalid PR URL: ${prUrl}`)
  }

  const number = prNumberFromUrl(prUrl)
  if (!number) {
    throw new Error(`Could not parse PR number from ${prUrl}`)
  }

  // Hard pre-admission checks: targets the base branch, not sent back.
  // These are the same checks mergePr does before entering the gate.
  const expectedBase = 'main' // TODO: determine base branch for non-marvin repos from their profile
  await assertTargetsBase(prUrl, exec, expectedBase)
  await assertNotSentBack(prUrl, exec)

  // Load existing queue
  const queue = readQueue(repo, dir)

  // Check if already queued or running
  const existing = queue.find(e => e.prUrl === prUrl && (e.status === 'queued' || e.status === 'running'))
  if (existing) {
    // Count how many are queued/running and before this one
    const position = queue.filter(e => (e.status === 'queued' || e.status === 'running')).findIndex(e => e.prUrl === prUrl) + 1
    return { queued: true, position, status: existing.status }
  }

  // Get ticket number for later stages logging (may be null)
  let ticketNumber = null
  try {
    const { stdout } = await exec('gh', ['pr', 'view', prUrl, '--json', 'body'])
    const body = JSON.parse(stdout).body || ''
    const m = body.match(/#(\d+)(?:\s|$)/)
    if (m) ticketNumber = parseInt(m[1], 10)
  } catch {
    // No ticket number found, that's ok
  }

  // Add to queue
  const entry = {
    prUrl,
    number,
    repo,
    ticketNumber,
    enqueuedAt: new Date().toISOString(),
    status: 'queued'
  }
  queue.push(entry)
  writeQueue(repo, queue, dir)

  // Kick the drain (asynchronous, don't wait)
  drain(repo, exec, dir).catch(err => {
    console.error(`[merge-queue] ${repo}: drain error: ${String(err.message || err).slice(0, 100)}`)
  })

  // Return position (1-indexed for display)
  const queuedRunning = queue.filter(e => e.status === 'queued' || e.status === 'running')
  const position = queuedRunning.length
  return { queued: true, position }
}

/**
 * Internal: process one repo's queue by draining one ready entry at a time.
 * Runs at most once concurrently per repo. Stops when no ready entries are found.
 * Returns a promise that resolves when the drain session completes (may be empty if already draining).
 */
async function drain(repo, exec, dir = QUEUE_DIR) {
  // Return existing drain if already running
  if (activeWrains.has(repo)) {
    return activeWrains.get(repo)
  }

  // Clear any existing poll timeout for this repo
  const existingTimeout = pollTimeouts.get(repo)
  if (existingTimeout) clearTimeout(existingTimeout)

  const drainPromise = (async () => {
    try {
      // Single drain session: process as many ready entries as we can find
      let keepDraining = true
      while (keepDraining) {
        const queue = readQueue(repo, dir)
        const queuedEntries = queue.filter(e => e.status === 'queued')

        if (queuedEntries.length === 0) {
          // No more queued entries
          keepDraining = false
          break
        }

        // Fetch open PRs to check readiness
        let openPrs = []
        try {
          openPrs = (await listOpenPrs()).filter(pr => (pr.repo || 'G-Eskayo/marvin') === repo)
        } catch (err) {
          // GitHub unreachable; stop draining and wait for next trigger
          console.error(`[merge-queue] ${repo}: failed to fetch open PRs: ${String(err.message || err).slice(0, 100)}`)
          keepDraining = false
          break
        }

        // Find the first queued entry whose dependencies are met
        let readyEntry = null
        for (const entry of queuedEntries) {
          const pr = openPrs.find(p => p.number === entry.number)
          if (!pr) {
            // PR is closed or not found; remove from queue and continue scanning
            const idx = queue.findIndex(e => e.prUrl === entry.prUrl && e.status === 'queued')
            if (idx >= 0) {
              queue.splice(idx, 1)
              writeQueue(repo, queue, dir)
            }
            continue
          }

          const deps = waitingOn(openPrs, pr)
          if (deps.length === 0) {
            // This PR is ready
            readyEntry = entry
            break
          }
        }

        if (!readyEntry) {
          // No ready entry found in this scan
          keepDraining = false
          break
        }

        // Mark as running, execute, then update result
        let queue2 = readQueue(repo, dir)
        const idx = queue2.findIndex(e => e.prUrl === readyEntry.prUrl)
        if (idx < 0) continue // Entry disappeared, move on

        queue2[idx].status = 'running'
        writeQueue(repo, queue2, dir)

        let result
        try {
          result = await mergePr(readyEntry.prUrl, exec)
        } catch (err) {
          // mergePr threw
          queue2[idx].status = 'failed'
          queue2[idx].result = { error: String(err.message || err) }
          writeQueue(repo, queue2, dir)
          // Continue to check for more ready entries
          continue
        }

        // mergePr returned (merged or reengaged)
        queue2[idx].status = 'done'
        queue2[idx].result = result
        writeQueue(repo, queue2, dir)
        // Loop to check for next ready entry
      }
    } finally {
      activeWrains.delete(repo)

      // Schedule a backstop poll to check again later (30s)
      const queue = readQueue(repo, dir)
      if (queue.some(e => e.status === 'queued')) {
        const timeout = setTimeout(() => {
          drain(repo, exec, dir).catch(err => {
            console.error(`[merge-queue] ${repo}: backstop poll failed: ${String(err.message || err).slice(0, 100)}`)
          })
        }, 30_000)
        pollTimeouts.set(repo, timeout)
      }
    }
  })()

  activeWrains.set(repo, drainPromise)
  return drainPromise
}
