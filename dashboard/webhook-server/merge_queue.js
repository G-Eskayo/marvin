import { readFileSync, writeFileSync, mkdirSync, renameSync } from 'fs'
import os from 'os'
import path from 'path'
import { mergeOrder } from './merge_order.js'

// The merge queue (marvin#231): Approve adds the PR to its repo's queue, and one runner per repo merges the queue in
// the order mergeOrder() works out, one PR at a time, through the existing gate (rebase onto the current main, the
// required checks, the decisions gate, merge). Desktop and phone approve into the same queue, because it lives here.
//
//   store:  ~/.claude/logs/merge-queue.json, rewritten whole through a temp file and a rename (like merge-inflight.json),
//           so a restart finds the queue as it was: { repos: { "owner/name": { items, failed, lastMerged } } }.
//           items: [{url, number, approvedAt, by}] (one per url: a second Approve, from either Mac, keeps the first's
//           place); failed: {url: {reason, code, at}} for PRs that left the queue failing, which their dependents name.
//   runner: drain(repo) — triggers only, never a timer: an Approve, a merge ending, the webhook's GitHub change pings
//           (PR updated, checks finished, main's CI) and startup. A trigger while it runs is remembered and run once more.
// Paths are worked out from os.homedir() at call time, so tests with a temp HOME never touch the real logs.

export const queuePath = () => path.join(os.homedir(), '.claude', 'logs', 'merge-queue.json')
const FAILED_KEEP = 50

const prNumber = (url) => Number(String(url).match(/\/pull\/(\d+)/)?.[1] ?? 0)

export function createQueueStore(file = queuePath(), { now = Date.now } = {}) {
  const read = () => {
    try {
      const v = JSON.parse(readFileSync(file, 'utf-8'))
      return v && typeof v === 'object' && v.repos && typeof v.repos === 'object' ? v : { repos: {} }
    } catch {
      return { repos: {} }
    }
  }
  const write = (all) => {
    mkdirSync(path.dirname(file), { recursive: true })
    const tmp = `${file}.${process.pid}.tmp`
    writeFileSync(tmp, JSON.stringify(all, null, 1))
    renameSync(tmp, file)
  }
  const repoOf = (all, repo) => {
    const r = all.repos[repo] || {}
    all.repos[repo] = { items: Array.isArray(r.items) ? r.items.filter((i) => i && typeof i.url === 'string') : [], failed: r.failed && typeof r.failed === 'object' ? r.failed : {}, lastMerged: r.lastMerged ?? null }
    return all.repos[repo]
  }
  const change = (repo, fn) => {
    const all = read()
    const out = fn(repoOf(all, repo))
    write(all)
    return out
  }
  return {
    forRepo: (repo) => repoOf(read(), repo),
    repos: () => Object.keys(read().repos).filter((r) => (read().repos[r]?.items || []).length),
    all: read,
    // Once per url: approving a PR already queued (the other Mac, the phone, a retry) keeps its place and time.
    add(repo, url, { by = 'you' } = {}) {
      return change(repo, (r) => {
        delete r.failed[url]
        const had = r.items.find((i) => i.url === url)
        if (had) return { added: false, item: had }
        const item = { url, number: prNumber(url), approvedAt: now(), by }
        r.items.push(item)
        return { added: true, item }
      })
    },
    remove(repo, url) {
      return change(repo, (r) => {
        const before = r.items.length
        r.items = r.items.filter((i) => i.url !== url)
        return r.items.length !== before
      })
    },
    merged(repo, url) {
      return change(repo, (r) => {
        r.items = r.items.filter((i) => i.url !== url)
        delete r.failed[url]
        r.lastMerged = prNumber(url)
      })
    },
    // The gate hit a conflict on this commit: it stays queued, held until the resolver (or anyone) pushes a new one.
    markConflict(repo, url, head) {
      return change(repo, (r) => {
        const it = r.items.find((i) => i.url === url)
        if (it) it.conflictHead = head || null
      })
    },
    fail(repo, url, { reason, code = null }) {
      return change(repo, (r) => {
        r.items = r.items.filter((i) => i.url !== url)
        r.failed[url] = { reason: String(reason || 'the merge failed').slice(0, 300), code, at: now() }
        const keep = Object.entries(r.failed).sort((a, b) => b[1].at - a[1].at).slice(0, FAILED_KEEP)
        r.failed = Object.fromEntries(keep)
      })
    }
  }
}

// What the outcome of one run means for the queue. A conflict stays queued: it goes to the #230 resolver and merges
// once fixed, with no second Approve. Anything else that did not merge leaves the queue with its reason.
const CONFLICT_CODES = new Set(['REBASE_CONFLICT', 'NOT_MERGEABLE'])
export function outcomeFor(outcome) {
  if (outcome?.result?.merged) return { kind: 'merged' }
  const r = outcome?.result
  const b = outcome?.body
  const code = r?.code || b?.code || null
  if (CONFLICT_CODES.has(code)) return { kind: 'conflict', code }
  const reason = r ? String(r.reason || 'sent back for rework').split('\n').find((l) => l.trim() && !/^\*\*/.test(l.trim())) || code || 'sent back for rework'
    : b?.message || b?.error || 'the merge failed'
  return { kind: 'failed', code, reason: code && r ? `${code}: ${reason}` : reason }
}

// load(repo) -> { openPrs (enriched), mainState }; run(url, attach) -> { result } | { body } (the merge, through the
// existing gate; `attach` is the Approve that asked for it, when it is still waiting for its answer); afterRun(repo):
// waits for the merge's after-steps (stacked PRs moved onto main, the others conflict-checked) before deciding again;
// onWaiting(repo, pr, entry): a queued PR is held by something MARVIN can act on (unbuilt answers, a conflict).
export function createMergeQueue({ store, load, run, afterRun = async () => {}, onWaiting = () => {}, log = () => {} }) {
  const busy = new Set()
  const again = new Set()
  const running = new Map() // repo -> url
  const views = new Map() // repo -> the last decision, for GET /merge-queue

  async function evaluate(repo) {
    const { openPrs, mainState } = await load(repo)
    const q = store.forRepo(repo)
    const out = mergeOrder(openPrs, mainState, { items: q.items, failed: q.failed, lastMerged: q.lastMerged, running: running.get(repo) || null })
    out.heads = new Map(openPrs.map((p) => [p.url, p.headRefOid || null]))
    for (const url of out.dropped) {
      // Merged or closed elsewhere (GitHub, the other Mac, by hand): it has nothing left to wait for.
      store.remove(repo, url)
      log(`[merge-queue] ${repo}: #${prNumber(url)} is no longer open; dropped from the queue`)
    }
    for (const p of openPrs) {
      const e = out.entries[p.url]
      if (e?.queued && e.state === 'waiting') { try { onWaiting(repo, p, e) } catch { /* a hint, never the decision */ } }
    }
    views.set(repo, { at: Date.now(), entries: out.entries, order: out.order, main: mainState, prs: openPrs })
    return out
  }

  // attach: { url, queued(entry) } — an Approve's request, answered at once with its place when it is not next.
  async function drain(repo, attach = null) {
    if (busy.has(repo)) {
      again.add(repo)
      // The runner is merging another PR: this Approve is told its place now (one read), and the runner takes it in turn.
      if (attach) {
        try { attach.queued((await evaluate(repo)).entries[attach.url] || null) } catch { attach.queued(null) }
      }
      return false
    }
    busy.add(repo)
    try {
      for (;;) {
        again.delete(repo)
        let out
        try {
          out = await evaluate(repo)
        } catch (e) {
          log(`[merge-queue] ${repo}: could not work out the order: ${String(e?.message || e).slice(0, 200)}`)
          if (attach) { attach.queued(null); attach = null }
          break
        }
        if (attach && attach.url !== out.next) { attach.queued(out.entries[attach.url] || null); attach = null }
        if (!out.next) {
          if (again.has(repo)) continue
          break
        }
        const url = out.next
        const mine = attach && attach.url === url ? attach : null
        attach = null
        running.set(repo, url)
        log(`[merge-queue] ${repo}: merging #${prNumber(url)} (${out.order.length} queued)`)
        let outcome
        try {
          outcome = await run(url, mine)
        } catch (e) {
          outcome = { body: { code: 'UNKNOWN', message: String(e?.message || e) } }
        } finally {
          running.delete(repo)
        }
        const o = outcomeFor(outcome)
        if (o.kind === 'merged') store.merged(repo, url)
        else if (o.kind === 'conflict') store.markConflict(repo, url, out.heads.get(url))
        else if (o.kind === 'failed') {
          store.fail(repo, url, { reason: o.reason, code: o.code })
          log(`[merge-queue] ${repo}: #${prNumber(url)} left the queue: ${o.reason}`)
        } else log(`[merge-queue] ${repo}: #${prNumber(url)} conflicts (${o.code}); it stays queued, held until a new commit (the resolver's)`)
        try { await afterRun(repo) } catch { /* the next decision reads GitHub as it is */ }
      }
    } finally {
      busy.delete(repo)
    }
    if (again.has(repo)) return drain(repo)
    return true
  }

  return {
    // An Approve: queued once per url; `attach` gets its place at once unless it runs now (then `run` answers it).
    approve(repo, url, { by = 'you', attach = null } = {}) {
      const { added, item } = store.add(repo, url, { by })
      if (!added) log(`[merge-queue] ${repo}: #${prNumber(url)} is already queued (approved ${new Date(item.approvedAt).toISOString()}); keeps its place`)
      return drain(repo, attach)
    },
    // Any trigger for one repo (GitHub changed, checks finished, startup). Nothing queued: nothing to do, no reads.
    kick(repo) {
      if (!store.forRepo(repo).items.length && !busy.has(repo)) return Promise.resolve(false)
      return drain(repo)
    },
    kickAll() {
      return Promise.all(store.repos().map((r) => this.kick(r)))
    },
    isRunning: (url) => [...running.values()].includes(url),
    runningIn: (repo) => running.get(repo) || null,
    view: (repo) => views.get(repo) || null,
    // For MR Review on either Mac: what is queued, what failed, and what runs now.
    snapshot() {
      const all = store.all()
      const repos = {}
      for (const [repo, r] of Object.entries(all.repos || {})) repos[repo] = { items: r.items || [], failed: r.failed || {}, lastMerged: r.lastMerged ?? null, running: running.get(repo) || null }
      for (const [repo, url] of running) if (!repos[repo]) repos[repo] = { items: [], failed: {}, lastMerged: null, running: url }
      return repos
    }
  }
}
