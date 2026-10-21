import { readFileSync } from 'fs'
import { homedir } from 'os'
import { join } from 'path'

// The dashboard's memory of GitHub: the last-known state of each repo (open PRs, board, completed work) and of the
// views that span every repo (queue, rework status). A read is answered from memory until GitHub says that repo
// changed -- the webhook server's change watch (webhook-server/gh_watch.js) checks every ~20 s with an ETag, and an
// unchanged answer costs nothing -- or the person's own action needs fresh data, or a 30-minute safety refresh.
// Tab switches and timers never reach GitHub on their own (Gil 2026-10-08, #318: the mini's dashboard made ~1,100
// GitHub calls an hour, because any change anywhere cleared every repo's cache). In memory only: one copy per repo.
const SAFETY_MS = 30 * 60_000
// #323: after a failed read, wait before asking GitHub again (1 min, doubling to 15), and never ask while the GitHub gate
// is cooling down. Before this, a refusal left nothing cached, so every screen refresh asked again: 517 refused calls in
// 20 minutes, 0.01 s apart, which went straight back to GitHub the moment the cooldown ended (2026-10-08).
const BACKOFF_MS = 60_000
const MAX_BACKOFF_MS = 15 * 60_000
const GATE_STATE = join(homedir(), '.claude', 'logs', 'gh-gate.json')

// When the GitHub gate (bin/gh) says every caller on this Mac must wait until, in ms; 0 when it doesn't.
export function gateCooldownUntil(file = process.env.MARVIN_GH_GATE_STATE || GATE_STATE) {
  try {
    return (JSON.parse(readFileSync(file, 'utf-8')).cooldown_until || 0) * 1000
  } catch {
    return 0
  }
}

// What a value's ttlFor asks for, in ms, or null (none, not a positive number, or it threw).
function ownTtl(ttlFor, value) {
  if (typeof ttlFor !== 'function') return null
  try {
    const ms = ttlFor(value)
    return Number.isFinite(ms) && ms > 0 ? ms : null
  } catch {
    return null
  }
}

export function createGithubState({ now = Date.now, safetyMs = SAFETY_MS, cooldownUntil = gateCooldownUntil } = {}) {
  const entries = new Map()   // `${kind}|${repo ?? '*'}` -> { value, at, gen, has, pending }
  const failures = new Map()  // same key -> { kind, repo, since, message } while its last read failed (#422)
  const gens = new Map()      // repo -> generation (bumped when GitHub says it changed)
  let allGen = 0              // bumped on any change: what values spanning every repo depend on
  let hits = 0
  let reads = 0

  const genOf = (repo) => (repo == null ? allGen : `${allGen}:${gens.get(repo) || 0}`)
  // a per-repo entry depends only on its repo; changedAll() bumps every repo too
  const currentGen = (repo) => (repo == null ? allGen : gens.get(repo) || 0)

  // ttlFor(value): a shorter lifetime the cached value itself asks for, e.g. a PR list with checks still running. GitHub
  // checks finishing is not an issue/PR update, so the change watch never pings for it (clarity-captions#143, 2026-10-21).
  async function get(kind, repo, fetch, { fresh = false, safetyMs: own, minIntervalMs = 0, ttlFor = null } = {}) {
    const key = `${kind}|${repo ?? '*'}`
    const e = entries.get(key) || { has: false }
    const ttl = Math.min(own ?? safetyMs, (e.has && ownTtl(ttlFor, e.value)) || Infinity)
    if (!fresh && e.has && e.gen === currentGen(repo) && now() - e.at < ttl) {
      hits += 1
      return e.value
    }
    // #324: a value spanning every repo need not follow every change ping; at most one re-read per interval.
    if (!fresh && e.has && minIntervalMs && now() - e.at < minIntervalMs) {
      hits += 1
      return e.value
    }
    if (!fresh && e.pending) return e.pending
    // #323: backing off after a failure, or the gate is cooling down: answer from memory, don't ask GitHub.
    const waitUntil = Math.max(e.retryAt || 0, cooldownUntil())
    if (!fresh && now() < waitUntil) {
      hits += 1
      if (e.has) return e.value
      throw e.error || new Error('GitHub is cooling down after a rate limit; trying again shortly')
    }
    const gen = currentGen(repo)
    reads += 1
    const pending = (async () => {
      try {
        const value = await fetch()
        entries.set(key, { value, at: now(), gen, has: true })
        failures.delete(key)
        return value
      } catch (err) {
        // GitHub refused or is unreachable: show what we last knew, and wait before asking again.
        const failCount = (e.failures || 0) + 1
        const retryAt = now() + Math.min(BACKOFF_MS * 2 ** (failCount - 1), MAX_BACKOFF_MS)
        entries.set(key, { ...e, pending: null, failures: failCount, retryAt, error: err })
        // marvin#422: remember which repos are being answered from an old copy (or not at all), so the screen can say so.
        if (!failures.has(key)) failures.set(key, { kind, repo, since: now() })
        failures.get(key).message = String(err?.message || err).split('\n')[0]
        if (e.has) return e.value
        throw err
      }
    })()
    entries.set(key, { ...e, pending })
    return pending
  }

  function changed(repo) {
    gens.set(repo, (gens.get(repo) || 0) + 1)
    allGen += 1
  }

  function changedAll() {
    for (const r of new Set([...gens.keys(), ...[...entries.keys()].map((k) => k.split('|')[1]).filter((r) => r !== '*')])) {
      gens.set(r, (gens.get(r) || 0) + 1)
    }
    allGen += 1
  }

  // Repos of one kind whose last read failed: [{repo, message, since}] (#422).
  function failing(kind) {
    return [...failures.values()].filter((f) => f.kind === kind).map(({ repo, message, since }) => ({ repo, message, since }))
  }

  return { get, changed, changedAll, failing, stats: () => ({ hits, reads, entries: entries.size }), _genOf: genOf }
}

// "github:owner/repo" (the change watch's ping source) -> "owner/repo"
export function repoOfSource(source) {
  const m = typeof source === 'string' ? source.match(/^github:([\w.-]+\/[\w.-]+)$/) : null
  return m ? m[1] : null
}
