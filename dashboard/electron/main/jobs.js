import { readFileSync, readdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

// Reads the run logs lib/job_events.py writes (one file per background job), for the
// Activity tab's "Background work" view: what each job is doing now and how recent runs went.
export const JOBS_DIR = path.join(homedir(), '.claude', 'logs', 'jobs')
const CRASHED_AFTER_MS = 30 * 60 * 1000 // must match job_events.CRASHED_AFTER_S
const SHOW_RUNS = 8

function statusOf(runs, now) {
  if (!runs.length) return 'never'
  const last = runs[runs.length - 1]
  if (last.status === 'running') {
    const started = Date.parse(last.started_at)
    return Number.isFinite(started) && now - started <= CRASHED_AFTER_MS ? 'running' : 'crashed'
  }
  return last.status === 'failed' ? 'failed' : 'idle'
}

const ORDER = { running: 0, crashed: 1, failed: 1, never: 3, idle: 2 }

function describe(doc, now) {
  const runs = (doc.runs || []).filter((r) => r && r.started_at)
  const status = statusOf(runs, now)
  const finishedRuns = runs.filter((r) => r.finished_at)
  const lastFinished = finishedRuns[finishedRuns.length - 1]
  const lastRun = runs[runs.length - 1]
  const current = status === 'running' ? { startedAt: lastRun.started_at, ...(lastRun.steps?.length ? lastRun.steps[lastRun.steps.length - 1] : { step: 'starting', detail: '' }) } : null
  return {
    job: doc.job,
    label: doc.label || doc.job,
    status,
    current,
    last: lastFinished
      ? {
          status: lastFinished.status,
          startedAt: lastFinished.started_at,
          finishedAt: lastFinished.finished_at,
          durationS: Math.round((Date.parse(lastFinished.finished_at) - Date.parse(lastFinished.started_at)) / 1000),
          summary: lastFinished.summary || '',
          error: lastFinished.error || ''
        }
      : null,
    runs: runs.slice(-SHOW_RUNS).reverse()
  }
}

export function listJobs({ dir = JOBS_DIR, now = Date.now() } = {}) {
  let names
  try {
    names = readdirSync(dir).filter((n) => n.endsWith('.json') && !n.startsWith('.'))
  } catch {
    return []
  }
  const jobs = []
  for (const n of names) {
    try {
      const doc = JSON.parse(readFileSync(path.join(dir, n), 'utf-8'))
      if (doc && doc.job) jobs.push(describe(doc, now))
    } catch {
      // a half-written or corrupt log is skipped, not fatal
    }
  }
  const recency = (j) => Date.parse(j.runs[0]?.started_at || 0) || 0
  return jobs.sort((a, b) => ORDER[a.status] - ORDER[b.status] || recency(b) - recency(a))
}
