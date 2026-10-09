// The dashboard's memory of GitHub: the last-known state of each repo (open PRs, board, completed work) and of the
// views that span every repo (queue, rework status). A read is answered from memory until GitHub says that repo
// changed -- the webhook server's change watch (webhook-server/gh_watch.js) checks every ~20 s with an ETag, and an
// unchanged answer costs nothing -- or the person's own action needs fresh data, or a 30-minute safety refresh.
// Tab switches and timers never reach GitHub on their own (Gil 2026-10-08, #318: the mini's dashboard made ~1,100
// GitHub calls an hour, because any change anywhere cleared every repo's cache). In memory only: one copy per repo.
const SAFETY_MS = 30 * 60_000

export function createGithubState({ now = Date.now, safetyMs = SAFETY_MS } = {}) {
  const entries = new Map()   // `${kind}|${repo ?? '*'}` -> { value, at, gen, has, pending }
  const gens = new Map()      // repo -> generation (bumped when GitHub says it changed)
  let allGen = 0              // bumped on any change: what values spanning every repo depend on
  let hits = 0
  let reads = 0

  const genOf = (repo) => (repo == null ? allGen : `${allGen}:${gens.get(repo) || 0}`)
  // a per-repo entry depends only on its repo; changedAll() bumps every repo too
  const currentGen = (repo) => (repo == null ? allGen : gens.get(repo) || 0)

  async function get(kind, repo, fetch, { fresh = false, safetyMs: own } = {}) {
    const key = `${kind}|${repo ?? '*'}`
    const e = entries.get(key) || { has: false }
    const ttl = own ?? safetyMs
    if (!fresh && e.has && e.gen === currentGen(repo) && now() - e.at < ttl) {
      hits += 1
      return e.value
    }
    if (!fresh && e.pending) return e.pending
    const gen = currentGen(repo)
    reads += 1
    const pending = (async () => {
      try {
        const value = await fetch()
        entries.set(key, { value, at: now(), gen, has: true })
        return value
      } catch (err) {
        entries.set(key, { ...e, pending: null })
        if (e.has) return e.value // GitHub refused or is unreachable: show what we last knew, retry next time
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

  return { get, changed, changedAll, stats: () => ({ hits, reads, entries: entries.size }), _genOf: genOf }
}

// "github:owner/repo" (the change watch's ping source) -> "owner/repo"
export function repoOfSource(source) {
  const m = typeof source === 'string' ? source.match(/^github:([\w.-]+\/[\w.-]+)$/) : null
  return m ? m[1] : null
}
