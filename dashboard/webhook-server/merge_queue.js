import { readFileSync, writeFileSync, mkdirSync, renameSync } from 'fs'
import os from 'os'
import path from 'path'
import { mergeOrder, HOLD_UNTIL, holdKey } from './merge_order.js'

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
        if (had) { delete had.hold; return { added: false, item: had } }
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
    // marvin#1097: a temporary refusal: it stays queued, held until `key` changes (or, for "later", until notBefore).
    hold(repo, url, hold) {
      return change(repo, (r) => {
        const it = r.items.find((i) => i.url === url)
        if (it) it.hold = hold
        delete r.failed[url]
      })
    },
    // The gate hit a conflict on this commit: it stays queued, held until the resolver (or anyone) pushes a new one.
    markConflict(repo, url, head, at = now()) {
      return change(repo, (r) => {
        const it = r.items.find((i) => i.url === url)
        if (!it) return
        if (it.conflictHead !== (head || null)) { it.conflictAt = at; delete it.conflictTold }
        it.conflictHead = head || null
      })
    },
    // marvin#1183: the owner was told this commit has been held on a conflict for a day; told once per commit.
    conflictTold(repo, url, head) {
      return change(repo, (r) => {
        const it = r.items.find((i) => i.url === url)
        if (it) it.conflictTold = head
      })
    },
    fail(repo, url, { reason, code = null }) {
      return change(repo, (r) => {
        r.items = r.items.filter((i) => i.url !== url)
        r.failed[url] = { reason: String(reason || 'the merge failed').slice(0, 300), code, at: now() }
        const keep = Object.entries(r.failed).sort((a, b) => b[1].at - a[1].at).slice(0, FAILED_KEEP)
        r.failed = Object.fromEntries(keep)
      })
    },
    // Resume an interrupted merge: re-add/move to front, clear stale hold/failed entry.
    resume(repo, url, { by = 'auto-resume' } = {}) {
      return change(repo, (r) => {
        delete r.failed[url]
        const had = r.items.find((i) => i.url === url)
        if (had) {
          delete had.hold
          const minTime = r.items.length > 0 ? Math.min(...r.items.map((i) => i.approvedAt)) : now()
          had.approvedAt = minTime - 1
          r.items.sort((a, b) => a.approvedAt - b.approvedAt)
          return { resumed: true, item: had }
        }
        const minTime = r.items.length > 0 ? Math.min(...r.items.map((i) => i.approvedAt)) : now()
        const item = { url, number: prNumber(url), approvedAt: minTime - 1, by }
        r.items.unshift(item)
        return { resumed: true, item }
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
  // marvin#1097: a temporary refusal holds the PR, queued, until what it waits on changes
  if (HOLD_UNTIL[code]) return { kind: 'hold', code, until: HOLD_UNTIL[code], reason: String(b?.message || r?.reason || code).split('\n')[0].slice(0, 200) }
  const reason = r ? String(r.reason || 'sent back for rework').split('\n').find((l) => l.trim() && !/^\*\*/.test(l.trim())) || code || 'sent back for rework'
    : b?.message || b?.error || 'the merge failed'
  return { kind: 'failed', code, reason: code && r ? `${code}: ${reason}` : reason }
}

// load(repo) -> { openPrs (enriched), mainState }; run(url, attach) -> { result } | { body } (the merge, through the
// existing gate; `attach` is the Approve that asked for it, when it is still waiting for its answer); afterRun(repo):
// waits for the merge's after-steps (stacked PRs moved onto main, the others conflict-checked) before deciding again;
// onWaiting(repo, pr, entry): a queued PR is held by something MARVIN can act on (unbuilt answers, a conflict).
export const HOLD_RETRY_MS = 5 * 60 * 1000   // a "later" hold's back-off (marvin#1097)
// marvin#1184: GitHub or the network failing. Held and retried like a "later" hold, but only so many times in a row,
// so a PR whose merge keeps failing still reaches the owner as a failure with its reason.
export const TEMPORARY_CODES = new Set(['RATE_LIMITED', 'GITHUB_OUTAGE', 'TRANSIENT_NETWORK', 'BASE_MOVED'])
export const TEMPORARY_TRIES = 6
const COOLDOWN_MAX_MS = 6 * 60 * 60 * 1000

// When a hold may next run: the default back-off, or a cooldown the refusal states ("cooldown until 11:44", the gh
// gate's wording) when that ends later today and within a few hours. A past or far-off time falls back to the default.
export function retryAt(reason, now) {
  const base = now + HOLD_RETRY_MS
  const m = /cooldown until (\d{1,2}):(\d{2})/i.exec(String(reason || ''))
  if (!m) return base
  const d = new Date(now)
  d.setHours(Number(m[1]), Number(m[2]), 0, 0)
  const t = d.getTime()
  if (!(t > now) || t - now > COOLDOWN_MAX_MS) return base
  return Math.max(t, base)
}

// marvin#1183: a PR held on the same conflicting commit this long is told to the owner (onStuck), once per commit.
export const CONFLICT_TELL_MS = 24 * 60 * 60 * 1000

export function createMergeQueue({ store, load, run, afterRun = async () => {}, onWaiting = () => {}, onStuck = () => {}, log = () => {}, clock = Date.now }) {
  const busy = new Set()
  const again = new Set()
  const running = new Map() // repo -> url
  const views = new Map() // repo -> the last decision, for GET /merge-queue

  async function evaluate(repo) {
    const { openPrs, mainState } = await load(repo)
    const q = store.forRepo(repo)
    const out = mergeOrder(openPrs, mainState, { items: q.items, failed: q.failed, lastMerged: q.lastMerged, running: running.get(repo) || null, now: clock() })
    out.heads = new Map(openPrs.map((p) => [p.url, p.headRefOid || null]))
    for (const url of out.dropped) {
      // Merged or closed elsewhere (GitHub, the other Mac, by hand): it has nothing left to wait for.
      store.remove(repo, url)
      log(`[merge-queue] ${repo}: #${prNumber(url)} is no longer open; dropped from the queue`)
    }
    for (const p of openPrs) {
      const e = out.entries[p.url]
      if (e?.queued && e.state === 'waiting') { try { onWaiting(repo, p, e) } catch { /* a hint, never the decision */ } }
      const it = q.items.find((i) => i.url === p.url)
      if (it?.conflictHead && it.conflictHead === p.headRefOid && it.conflictTold !== it.conflictHead &&
          Number.isFinite(it.conflictAt) && clock() - it.conflictAt >= CONFLICT_TELL_MS) {
        store.conflictTold(repo, p.url, it.conflictHead)
        log(`[merge-queue] ${repo}: #${p.number} has been held on a conflict for a day; telling the owner`)
        try { onStuck(repo, p, { head: it.conflictHead, since: it.conflictAt }) } catch { /* telling never stops the queue */ }
      }
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
        else if (o.kind === 'conflict') store.markConflict(repo, url, out.heads.get(url), clock())
        else if (o.kind === 'hold') {
          const v = views.get(repo)
          const pr = (v?.prs || []).find((p) => p.url === url)
          const key = holdKey(o.until, pr, v?.main)
          const temporary = TEMPORARY_CODES.has(o.code)
          const prev = store.forRepo(repo).items.find((i) => i.url === url)?.hold
          const tries = temporary ? (prev?.code === o.code ? (Number(prev.tries) || 0) + 1 : 1) : null
          if (temporary && tries >= TEMPORARY_TRIES) {
            store.fail(repo, url, { reason: `${o.reason} (after ${tries} tries)`, code: o.code })
            log(`[merge-queue] ${repo}: #${prNumber(url)} left the queue after ${tries} tries (${o.code}): ${o.reason}`)
          } else {
            const notBefore = o.until === 'later' || key == null ? (temporary ? retryAt(o.reason, clock()) : clock() + HOLD_RETRY_MS) : null
            store.hold(repo, url, { code: o.code, until: o.until, reason: o.reason, key, notBefore, at: clock(), ...(temporary ? { tries } : {}) })
            log(`[merge-queue] ${repo}: #${prNumber(url)} held (${o.code}${temporary ? `, try ${tries} of ${TEMPORARY_TRIES}` : ''}): ${o.reason}`)
          }
        }
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
