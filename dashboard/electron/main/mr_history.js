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
const MAX_NOTES = 3

export function buildRows(merged, history, openPrs = [], closedPrs = []) {
  const by = new Map((history?.merges || []).map((m) => [m.pr_url, m.by]))
  const titles = new Map([...(openPrs || []), ...(closedPrs || []), ...(merged || [])].map((p) => [p.url, p.title]))

  // Build a map keyed by PR url
  const rows = new Map()

  // Build refusal groups by URL for all refusals (not just those in open list)
  const refusalsByUrl = new Map()
  for (const r of history?.refusals || []) {
    if (!refusalsByUrl.has(r.pr_url)) refusalsByUrl.set(r.pr_url, [])
    refusalsByUrl.get(r.pr_url).push(r)
  }

  // Dropped rows from closedPrs (no mergedAt, so rejected/closed but not merged)
  // If closed PR has refusals, fold them into notes
  for (const p of closedPrs || []) {
    if (!p.mergedAt && p.closedAt) {
      const refusals = refusalsByUrl.get(p.url) || []
      rows.set(p.url, {
        kind: 'dropped',
        url: p.url,
        number: p.number,
        title: p.title,
        repo: p.repo,
        at: p.closedAt,
        notes: refusals.slice(-MAX_NOTES).map((r) => ({ code: r.code, reason: plainReason(r.code), message: r.message || '', at: r.t })),
        refusalCount: refusals.length
      })
    }
  }

  // Open rows from openPrs with refusals
  for (const p of openPrs || []) {
    const refusals = refusalsByUrl.get(p.url) || []
    if (refusals.length) {
      const m = PR_RE.exec(p.url)
      const latest = refusals[refusals.length - 1]
      rows.set(p.url, {
        kind: 'open',
        url: p.url,
        number: p.number || (m ? parseInt(m[2]) : undefined),
        title: p.title,
        repo: p.repo || (m ? m[1] : undefined),
        at: latest.t,
        notes: refusals.slice(-MAX_NOTES).map((r) => ({ code: r.code, reason: plainReason(r.code), message: r.message || '', at: r.t })),
        plainReason: plainReason(latest.code),
        refusalCount: refusals.length
      })
    }
  }

  // Merged rows (overwriting any dropped/open entry for same url)
  // If merged PR has refusals, fold them into notes
  for (const p of merged || []) {
    const refusals = refusalsByUrl.get(p.url) || []
    rows.set(p.url, {
      kind: 'merged',
      url: p.url,
      number: p.number,
      title: p.title,
      repo: p.repo,
      at: p.mergedAt,
      by: by.get(p.url) || 'unrecorded',
      notes: refusals.slice(-MAX_NOTES).map((r) => ({ code: r.code, reason: plainReason(r.code), message: r.message || '', at: r.t })),
      refusalCount: refusals.length
    })
  }

  // Convert map to sorted array
  const result = [...rows.values()]
  const t = (x) => (Number.isNaN(Date.parse(x.at)) ? -Infinity : Date.parse(x.at))
  return result.sort((a, b) => t(b) - t(a))
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
  return (loadCache(file)?.merged || []).map((p) => ({ url: p.url, at: p.mergedAt }))
}

// The dropped (closed but not merged) PRs the Merged view last saved, as {url, at}
export function readSavedClosed(file) {
  return (loadCache(file)?.closed || []).filter((p) => !p.mergedAt).map((p) => ({ url: p.url, at: p.closedAt }))
}

function saveCache(file, cache) {
  try {
    mkdirSync(path.dirname(file), { recursive: true })
    const tmp = `${file}.${process.pid}.tmp`
    writeFileSync(tmp, JSON.stringify(cache))
    renameSync(tmp, file)
  } catch { /* the view still works; next launch just reads GitHub again */ }
}

export function createMrHistory({ repos, ghList, ghListClosed, webhookHistory, openPrs, cachePath, now = Date.now }) {
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

      // Track high-water mark of closedAt across merged and closed PRs, since both have been closed
      const newestMergedClosed = (cache.merged || []).filter((p) => p.repo === repo).map((p) => p.mergedAt).sort().pop() || null
      const newestDroppedClosed = (cache.closed || []).filter((p) => p.repo === repo).map((p) => p.closedAt).sort().pop() || null
      const newestClosed = [newestMergedClosed, newestDroppedClosed].filter(Boolean).sort().pop() || null
      try {
        for (const p of (await ghListClosed(repo, newestClosed)) || []) if (p?.url && !p.mergedAt) closedByUrl.set(p.url, { ...p, repo })
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

    const next = {
      merged: [...byUrl.values()],
      closed: [...closedByUrl.values()],
      history,
      open: open.map((p) => {
        const m = PR_RE.exec(p.url)
        return { url: p.url, number: p.number || (m ? parseInt(m[2]) : undefined), repo: p.repo || (m ? m[1] : undefined), title: p.title, createdAt: p.createdAt }
      }),
      updatedAt: now()
    }
    saveCache(cachePath, next)
    return { rows: buildRows(next.merged, history, next.open, next.closed), updatedAt: next.updatedAt, errors }
  }

  return {
    async get({ fresh = false } = {}) {
      if (!fresh) {
        const c = loadCache(cachePath)
        return c ? { rows: buildRows(c.merged, c.history, c.open, c.closed), updatedAt: c.updatedAt, errors: [] } : { rows: [], updatedAt: null, errors: [] }
      }
      if (!inflight) inflight = refresh().finally(() => { inflight = null })
      return inflight
    }
  }
}
