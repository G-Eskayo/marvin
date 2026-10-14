import { appendFileSync, mkdirSync, readFileSync, readdirSync } from 'fs'
import path from 'path'
import os from 'os'

// MR Review's Merged view (marvin#419): what this merge server merged, and every Approve it refused or failed.
// Merges are recorded going forward in merge-history.jsonl; older ones are recovered from the ticket stage logs
// ("merged: <url>"). Refusals come from the approve-failed lines in the server's own log (the only place some codes,
// like MAIN_RED, are written) and from pipeline-failures.jsonl. Fail-soft throughout: history must never break a merge.

const LOGS = () => path.join(os.homedir(), '.claude', 'logs')
export const defaultPaths = () => ({
  mergeFile: path.join(LOGS(), 'merge-history.jsonl'),
  failuresFile: path.join(LOGS(), 'pipeline-failures.jsonl'),
  // approve-failed lines are written with console.error, so they land in the error log; read both.
  webhookLog: [path.join(LOGS(), 'dashboard-webhook-error.log'), path.join(LOGS(), 'dashboard-webhook.log')],
  stagesDir: path.join(LOGS(), 'ticket-stages')
})

const PR_URL = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/\d+$/

export function appendMerge(prUrl, by, { file = defaultPaths().mergeFile, now = () => new Date() } = {}) {
  try {
    mkdirSync(path.dirname(file), { recursive: true })
    appendFileSync(file, JSON.stringify({ t: now().toISOString(), pr_url: prUrl, by }) + '\n')
  } catch { /* fail-soft */ }
}

function lines(file) {
  try {
    return readFileSync(file, 'utf-8').split('\n')
  } catch {
    return []
  }
}

function jsonLines(file) {
  const out = []
  for (const l of lines(file)) {
    if (!l.trim()) continue
    try {
      const v = JSON.parse(l)
      if (v && typeof v === 'object') out.push(v)
    } catch { /* skip */ }
  }
  return out
}

const APPROVE_FAILED = /^(\S+) approve failed: (\S+) ([A-Z_]+) at [\w-]+: (.*)$/

export function readMergeHistory(paths = defaultPaths()) {
  const merges = []
  for (const r of jsonLines(paths.mergeFile)) {
    if (PR_URL.test(r.pr_url || '') && r.t) merges.push({ pr_url: r.pr_url, t: r.t, by: r.by || 'you' })
  }
  const known = new Set(merges.map((m) => m.pr_url))
  if (paths.stagesDir) {
    let files = []
    try { files = readdirSync(paths.stagesDir).filter((f) => f.endsWith('.json')) } catch { files = [] }
    for (const f of files) {
      let events
      try { events = JSON.parse(readFileSync(path.join(paths.stagesDir, f), 'utf-8')) } catch { continue }
      for (const e of Array.isArray(events) ? events : []) {
        const m = /^merged: (\S+)$/.exec(e?.detail || '')
        if (e?.stage === 'done' && e?.status === 'passed' && m && PR_URL.test(m[1]) && !known.has(m[1])) {
          merges.push({ pr_url: m[1], t: e.timestamp, by: 'you' })
          known.add(m[1])
        }
      }
    }
  }

  const refusals = []
  for (const l of [].concat(paths.webhookLog || []).flatMap(lines)) {
    const m = APPROVE_FAILED.exec(l.trim())
    if (m && PR_URL.test(m[2]) && !Number.isNaN(Date.parse(m[1])) && !refusals.some((x) => x.pr_url === m[2] && x.t === m[1] && x.code === m[3])) {
      refusals.push({ pr_url: m[2], t: m[1], code: m[3], message: m[4] })
    }
  }
  for (const r of jsonLines(paths.failuresFile)) {
    if (!PR_URL.test(r.pr_url || '') || !r.t) continue
    const code = String(r.sig || '').replace(/^merge:/, '') || 'FAILED'
    const dup = refusals.some((x) => x.pr_url === r.pr_url && x.code === code && Math.abs(Date.parse(x.t) - Date.parse(r.t)) <= 120_000)
    if (!dup) refusals.push({ pr_url: r.pr_url, t: r.t, code, message: String(r.reason || '').replace(/^[A-Z_]+: /, '') })
  }
  refusals.sort((a, b) => Date.parse(a.t) - Date.parse(b.t))
  return { merges, refusals }
}
