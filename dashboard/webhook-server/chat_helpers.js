import { readFileSync, readdirSync, statSync } from 'fs'
import os from 'os'
import path from 'path'

// Helpers a chat started with the Agent tool (#612), read from the run logs lib/chat_helpers.py's hooks write
// (~/.claude/logs/jobs/helper-<agent id>.json, the job_events format plus a `helper` block). Served here at
// GET /helpers so the other Mac's dashboard can show them (the same channel as GET /sessions, #331), and read
// directly by this Mac's dashboard. Status is decided on the Mac that ran the helper, because a helper killed
// mid-run sends no stop event and only that Mac can see its transcript go quiet.
export const HELPERS_DIR = path.join(os.homedir(), '.claude', 'logs', 'jobs')
export const STALE_MS = 15 * 60 * 1000 // must match chat_helpers.STALE_S
const PREFIX = 'helper-'

const ms = (iso) => {
  const t = Date.parse(iso)
  return Number.isFinite(t) ? t : null
}

// done | failed | running | crashed (a running helper whose transcript has been quiet for STALE_MS).
export function helperStatus(run, transcriptMtimeMs, now) {
  if (run.status === 'passed') return 'done'
  if (run.status !== 'running') return 'failed'
  const beat = Math.max(ms(run.started_at) || 0, transcriptMtimeMs || 0)
  return now - beat <= STALE_MS ? 'running' : 'crashed'
}

const cleanLinks = (links) =>
  (Array.isArray(links) ? links : [])
    .filter((l) => l && (l.kind === 'ticket' || l.kind === 'pr') && /^[\w.-]+\/[\w.-]+$/.test(l.repo || '') && Number.isInteger(l.number))
    .map((l) => ({ kind: l.kind, repo: l.repo, number: l.number }))

// One helper as the agent rows render it (AgentsPanel's AgentCard: label, status, current, last, runs).
export function describeHelper(doc, { now = Date.now(), mtime = () => null } = {}) {
  const run = Array.isArray(doc?.runs) ? doc.runs[doc.runs.length - 1] : null
  if (!run || !run.started_at || typeof doc.helper !== 'object' || !doc.helper) return null
  const h = doc.helper
  const transcriptMs = typeof h.transcript === 'string' && h.transcript ? mtime(h.transcript) : null
  const status = helperStatus(run, transcriptMs, now)
  const finished = status === 'done' || status === 'failed'
  const startedMs = ms(run.started_at)
  const finishedMs = ms(run.finished_at)
  const step = Array.isArray(run.steps) && run.steps.length ? run.steps[run.steps.length - 1] : { step: 'working', detail: '' }
  const machine = String(h.machine || '')
  const chat = String(h.chat || '')
  return {
    id: String(doc.job),
    label: String(doc.label || doc.job),
    kind: 'helper',
    schedule: [chat ? `from “${chat.length > 60 ? chat.slice(0, 59) + '…' : chat}”` : 'from a chat', machine && `on ${machine}`].filter(Boolean).join(' '),
    status,
    running: status === 'running',
    reporting: true,
    machine,
    session: String(h.session || ''),
    startedAt: run.started_at,
    links: cleanLinks(h.links),
    job: {
      job: String(doc.job),
      label: String(doc.label || doc.job),
      status,
      current: status === 'running' ? { startedAt: run.started_at, step: step.step, detail: step.detail || '' } : null,
      last: finished
        ? {
            status: status === 'done' ? 'passed' : 'failed',
            startedAt: run.started_at,
            finishedAt: run.finished_at || run.started_at,
            durationS: startedMs && finishedMs ? Math.max(0, Math.round((finishedMs - startedMs) / 1000)) : 0,
            summary: typeof run.summary === 'string' ? run.summary : '',
            error: typeof run.error === 'string' ? run.error : ''
          }
        : status === 'crashed'
          ? {
              status: 'failed',
              startedAt: run.started_at,
              finishedAt: new Date(Math.max(startedMs || 0, transcriptMs || 0)).toISOString(), // its last sign of life
              durationS: Math.max(0, Math.round(((transcriptMs || startedMs || 0) - (startedMs || 0)) / 1000)),
              summary: '',
              error: 'no word from it for 15 min: probably stopped with its chat'
            }
          : null,
      runs: [{ ...run, steps: Array.isArray(run.steps) ? run.steps : [] }]
    }
  }
}

const RANK = { running: 0, crashed: 1, failed: 1, done: 2 }

export function listHelpers({ dir = HELPERS_DIR, now = Date.now() } = {}) {
  let names
  try {
    names = readdirSync(dir).filter((n) => n.startsWith(PREFIX) && n.endsWith('.json'))
  } catch {
    return []
  }
  const mtime = (p) => {
    try {
      return statSync(p).mtimeMs
    } catch {
      return null
    }
  }
  const out = []
  for (const n of names) {
    try {
      const h = describeHelper(JSON.parse(readFileSync(path.join(dir, n), 'utf-8')), { now, mtime })
      if (h) out.push(h)
    } catch {
      // a half-written or corrupt log is skipped, not fatal
    }
  }
  return sortHelpers(out)
}

export function sortHelpers(list) {
  return [...list].sort((a, b) => RANK[a.status] - RANK[b.status] || String(b.startedAt).localeCompare(String(a.startedAt)))
}
