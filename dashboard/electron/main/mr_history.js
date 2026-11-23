import { readFileSync, writeFileSync, renameSync, mkdirSync } from 'fs'
import path from 'path'

// MR Review's Merged view (marvin#419): every merged PR across registered projects, who merged it, and every refused
// Approve, newest first. History only grows, so GitHub is asked only for PRs merged since the newest one already
// known (a day of overlap, deduped by url), and the result is saved: opening the view answers from the saved copy at
// once, and a fresh read replaces it. Who merged: 'you' (dashboard Approve) or 'auto' from the merge server's record;
// merges it has no record of (before #419, or done on GitHub directly) are 'unrecorded' rather than guessed.

export function mergedPrArgs(repo, since) {
  const args = ['pr', 'list', '--repo', repo, '--state', 'merged', '--limit', '1000', '--json', 'number,title,url,mergedAt']
  if (!since) return args
  const day = new Date(Date.parse(since) - 86_400_000).toISOString().slice(0, 10)
  return [...args, '--search', `merged:>=${day}`]
}

export function closedPrArgs(repo, since) {
  const args = ['pr', 'list', '--repo', repo, '--state', 'closed', '--limit', '1000', '--json', 'number,title,url,closedAt,mergedAt']
  if (!since) return args
  const day = new Date(Date.parse(since) - 86_400_000).toISOString().slice(0, 10)
  return [...args, '--search', `closed:>=${day}`]
}

const REASONS = {
  MAIN_RED: 'main was failing', GATE_TESTS_FAILED: 'tests failed', GATE_INFRA: 'the build machine failed', MEMORY_PRESSURE: 'waiting for memory', OUT_OF_ORDER: 'merge another PR first',
  CI_PENDING: 'checks still running', CI_FAILED: 'GitHub checks failed', SENT_BACK: 'sent back for rework', WRONG_BASE: 'wrong base branch',
  NO_UI_EVIDENCE: 'needed screenshots', DECISIONS_PENDING: 'decisions not answered',
  NO_MERGE_PROFILE: 'this project can’t merge from the dashboard', MERGE_REFUSED: 'GitHub refused the merge', REBASE_CONFLICT: 'conflicts after rebase'
}
export const plainReason = (code) => REASONS[code] || code

const PR_RE = /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/pull\/(\d+)$/

export function buildRows({ merged = [], closed = [], openPrs = [], history = {} } = {}) {
  const by = new Map((history.merges || []).map((m) => [m.pr_url, m.by]))
  const titles = new Map([...(openPrs || []), ...(merged || []), ...(closed || [])].map((p) => [p.url, p.title]))

  // Build refusals map: pr_url -> [{at, reason, code, message}]
  const refusalsByUrl = new Map()
  for (const r of history.refusals || []) {
    const m = PR_RE.exec(r.pr_url || '')
    if (!m) continue
    if (!refusalsByUrl.has(r.pr_url)) refusalsByUrl.set(r.pr_url, [])
    refusalsByUrl.get(r.pr_url).push({ at: r.t, reason: plainReason(r.code), code: r.code, message: r.message || '' })
  }

  // Sort each PR's refusals newest first
  for (const [url, notes] of refusalsByUrl) {
    notes.sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
  }

  const rows = []
  const seenUrls = new Set()

  // Merged PRs: always show, with any attached refusals
  for (const p of merged || []) {
    const notes = refusalsByUrl.get(p.url) || []
    rows.push({ kind: 'merged', url: p.url, number: p.number, title: p.title, repo: p.repo, at: p.mergedAt, by: by.get(p.url) || 'unrecorded', notes })
    seenUrls.add(p.url)
  }

  // Open PRs from the live list: only show if they have refusals
  for (const p of openPrs || []) {
    const notes = refusalsByUrl.get(p.url) || []
    if (notes.length) {
      rows.push({ kind: 'open', url: p.url, number: p.number, title: p.title, repo: p.repo, at: p.createdAt, notes })
      seenUrls.add(p.url)
    }
  }

  // Closed PRs: show if not already merged, with any attached refusals
  for (const p of closed || []) {
    if (seenUrls.has(p.url)) continue
    if (p.mergedAt) continue // it merged, already in merged list
    const notes = refusalsByUrl.get(p.url) || []
    rows.push({ kind: 'dropped', url: p.url, number: p.number, title: p.title, repo: p.repo, at: p.closedAt, notes })
    seenUrls.add(p.url)
  }

  const t = (x) => (Number.isNaN(Date.parse(x.at)) ? -Infinity : Date.parse(x.at))
  return rows.sort((a, b) => t(b) - t(a))
}

function loadCache(file) {
  try {
    const c = JSON.parse(readFileSync(file, 'utf-8'))
    return c && Array.isArray(c.merged) && typeof c.updatedAt === 'number' ? c : null
  } catch {
    return null
  }
}

// The merged PRs the Merged view last saved, as {url, at}: Activity's projects list reads these, never GitHub.
export function readSavedMerged(file) {
  return (loadCache(file)?.merged || []).map((p) => ({ url: p.url, at: p.mergedAt || p.at }))
}

function saveCache(file, cache) {
  try {
    mkdirSync(path.dirname(file), { recursive: true })
    const tmp = `${file}.${process.pid}.tmp`
    writeFileSync(tmp, JSON.stringify(cache))
    renameSync(tmp, file)
  } catch { /* the view still works; next launch just reads GitHub again */ }
}

export function createMrHistory({ repos, ghList, ghListClosed = async () => [], webhookHistory, openPrs, cachePath, now = Date.now }) {
  let inflight = null

  async function refresh() {
    const cache = loadCache(cachePath) || { merged: [], closed: [], updatedAt: 0, history: { merges: [], refusals: [] } }
    const errors = []
    const byUrl = new Map(cache.merged.map((p) => [p.url, p]))
    const closedByUrl = new Map((cache.closed || []).map((p) => [p.url, p]))

    for (const repo of repos()) {
      const newest = cache.merged.filter((p) => p.repo === repo).map((p) => p.mergedAt).sort().pop() || null
      try {
        for (const p of (await ghList(repo, newest)) || []) if (p?.url) byUrl.set(p.url, { ...p, repo })
      } catch (err) {
        errors.push({ repo, message: err?.message || String(err) })
      }

      const newestClosed = (cache.closed || []).filter((p) => p.repo === repo).map((p) => p.closedAt).sort().pop() || null
      try {
        for (const p of (await ghListClosed(repo, newestClosed)) || []) if (p?.url) closedByUrl.set(p.url, { ...p, repo })
      } catch (err) {
        errors.push({ repo, message: err?.message || String(err) })
      }
    }

    let history = cache.history || { merges: [], refusals: [] }
    try {
      history = (await webhookHistory()) || history
    } catch (err) {
      errors.push({ repo: 'merge server', message: err?.message || String(err) })
    }

    let open = []
    try { open = (await openPrs()) || [] } catch { open = [] }

    const next = { merged: [...byUrl.values()], closed: [...closedByUrl.values()], history, open: open.map((p) => ({ url: p.url, number: p.number, repo: p.repo, title: p.title, createdAt: p.createdAt })), updatedAt: now() }
    saveCache(cachePath, next)
    return { rows: buildRows({ merged: next.merged, closed: next.closed, openPrs: next.open, history }), updatedAt: next.updatedAt, errors }
  }

  return {
    async get({ fresh = false } = {}) {
      if (!fresh) {
        const c = loadCache(cachePath)
        return c ? { rows: buildRows({ merged: c.merged, closed: c.closed || [], openPrs: c.open, history: c.history }), updatedAt: c.updatedAt, errors: [] } : { rows: [], updatedAt: null, errors: [] }
      }
      if (!inflight) inflight = refresh().finally(() => { inflight = null })
      return inflight
    }
  }
}
