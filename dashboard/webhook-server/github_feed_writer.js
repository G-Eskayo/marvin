import { readFileSync, writeFileSync, renameSync, mkdirSync, unlinkSync } from 'fs'
import { dirname } from 'path'
import { FEED_PATH } from '../electron/main/github_feed.js'
import { prListArgs, pendingCheckHeads } from '../electron/main/mr_repos.js'
import { fetchBoardData } from '../electron/main/boards.js'

// marvin#954: the Mini's half of the box's GitHub view (electron/main/github_feed.js has the shape and the box half).
// The webhook server runs here all the time with the shared GitHub credential, and its change watch already asks
// GitHub every ~20 s with an ETag (free when nothing changed). This writes, per registered repo, what the MR list and
// the board would read, so mac-mini-2012 (no credential, ADR 0069) can show it:
//   - on startup, every repo once;
//   - on a change ping for a repo, that repo (coalesced: one read in flight per repo, one queued behind it);
//   - on a check change for one of the feed's own pending PRs, that repo's PR list;
//   - after each quiet watch round, only `alive_at` (at most once a minute), so the box can tell quiet from dead.
// No timer of its own. Cost per change: one `gh pr list` plus the board's 2-3 issue lists (the board's own PR list is
// answered from the full list just read). Written atomically, mode 600; only `gh` output goes in, never a credential.

const ALIVE_EVERY_MS = 60_000
const BOARD_PR_FIELDS = ['number', 'title', 'url', 'isDraft', 'body', 'files']

export function emptyFeed(host) {
  return { version: 1, host: host || null, alive_at: null, repos: {} }
}

export function createGithubFeedWriter({
  path = FEED_PATH,
  repos,
  gh,
  host = null,
  now = Date.now,
  read = (p) => readFileSync(p, 'utf-8'),
  write = atomicWrite,
  log = (m) => console.log(m)
}) {
  let feed = (() => {
    try {
      const f = JSON.parse(read(path))
      return f && typeof f === 'object' && f.repos && typeof f.repos === 'object' && !Array.isArray(f.repos) ? { ...emptyFeed(host), ...f, host } : emptyFeed(host)
    } catch {
      return emptyFeed(host)
    }
  })()
  let lastAliveWrite = 0
  const inflight = new Map() // repo -> { running: Promise, again: boolean, prsOnly: boolean }

  const save = () => {
    const keep = new Set(repos())
    for (const r of Object.keys(feed.repos)) if (!keep.has(r)) delete feed.repos[r]
    write(path, JSON.stringify(feed))
  }

  async function readRepo(repo, prsOnly) {
    const prs = JSON.parse(await gh(prListArgs(repo, { light: false })))
    const at = now()
    const entry = { ...(feed.repos[repo] || {}), prs: { at, value: prs } }
    if (!prsOnly) {
      // The board's own PR list is the list just read, cut to its fields (it asks for --state open --limit 100).
      const boardGh = async (args) => {
        if (args[0] === 'pr' && args[1] === 'list') {
          return JSON.stringify(prs.slice(0, 100).map((p) => ({ ...Object.fromEntries(BOARD_PR_FIELDS.map((f) => [f, p[f]])), state: 'OPEN' })))
        }
        return gh(args)
      }
      entry.board = { at: now(), value: await fetchBoardData(repo, boardGh) }
    }
    feed.repos[repo] = entry
    feed.alive_at = now()
    save()
  }

  // Coalesced per repo: a ping while a read runs queues exactly one more (a full one wins over a PR-only one).
  function refresh(repo, { prsOnly = false } = {}) {
    if (!repos().includes(repo)) return Promise.resolve(false)
    const cur = inflight.get(repo)
    if (cur) {
      cur.again = true
      cur.prsOnly = cur.prsOnly && prsOnly
      return cur.running
    }
    const state = { again: false, prsOnly: true, running: null }
    state.running = (async () => {
      let only = prsOnly
      try {
        for (;;) {
          try {
            await readRepo(repo, only)
          } catch (err) {
            // GitHub refused or is unreachable: keep the last good entry; alive_at stops moving, which the box shows.
            log(`[github-feed] could not read ${repo}: ${String(err?.message || err).split('\n')[0].slice(0, 160)}`)
          }
          if (!state.again) return true
          only = state.prsOnly
          state.again = false
          state.prsOnly = true
        }
      } finally {
        inflight.delete(repo)
      }
    })()
    inflight.set(repo, state)
    return state.running
  }

  async function refreshAll() {
    for (const repo of repos()) await refresh(repo)
  }

  // A watch round finished: if GitHub answered for any repo (changed or not), note it, at most once a minute. A round
  // where nothing answered (the Mini offline, GitHub down, rate-limited) leaves alive_at alone, so the box sees it age.
  function alive(answered = 1) {
    if (!(answered > 0)) return false
    const t = now()
    if (t - lastAliveWrite < ALIVE_EVERY_MS) return false
    lastAliveWrite = t
    feed.alive_at = t
    try {
      save()
    } catch (err) {
      log(`[github-feed] could not write: ${err?.message || err}`)
    }
    return true
  }

  // Commits whose checks are still running, from the feed's own lists: what the check watch asks about.
  const pendingHeads = () => Object.entries(feed.repos).flatMap(([repo, e]) => pendingCheckHeads(repo, e?.prs?.value))

  return { refresh, refreshAll, alive, pendingHeads, current: () => feed }
}

// Temp file + rename in the same folder: a reader (the observer `cat`) sees the old file or the new one, never half.
export function atomicWrite(path, text) {
  mkdirSync(dirname(path), { recursive: true })
  const tmp = `${path}.${process.pid}.tmp`
  try {
    writeFileSync(tmp, text, { mode: 0o600 })
    renameSync(tmp, path)
  } catch (err) {
    try { unlinkSync(tmp) } catch { /* nothing to clean */ }
    throw err
  }
}
