import { checkRuns } from './ci_status.js'

// GitHub change-detector: the trigger for "something changed on a board repo",
// whoever changed it (another chat, the other machine, raw `gh`, the web UI).
//
// One conditional request per repo against its most-recently-updated issue
// (PRs are issues too, and labels/comments/state changes all bump it). An
// unchanged answer is a 304, which GitHub does not count against the rate
// limit, so polling every ~20s is effectively free. Chosen over real GitHub
// webhooks (need a public URL; the only static ngrok domain is Marlin's) and
// over the events feed (lags by minutes). See CONTEXT.md "Triggers over polling".
export function issuesEndpoint(repo) {
  return `https://api.github.com/repos/${repo}/issues?state=all&sort=updated&direction=desc&per_page=1`
}

export function createChangeDetector({ probe, onChange }) {
  const etags = new Map()

  async function tick(repos) {
    for (const known of [...etags.keys()]) {
      if (!repos.includes(known)) etags.delete(known)
    }
    for (const repo of repos) {
      let res
      try {
        res = await probe(repo, etags.get(repo))
      } catch {
        continue // offline / rate-limited: keep the last etag, try next tick
      }
      if (res.status !== 200 || !res.etag) continue // 304 = unchanged; anything else = ignore
      const previous = etags.get(repo)
      etags.set(repo, res.etag)
      if (previous !== undefined && previous !== res.etag) onChange(repo)
    }
  }

  return { tick }
}

// Real probe: authenticated conditional GET using the shared pipeline token (gh_auth.js).
export function createGithubProbe(env = process.env, doFetch = fetch) {
  return async (repo, etag) => {
    const headers = { Accept: 'application/vnd.github+json', 'User-Agent': 'marvin-dashboard-watch' }
    if (env.GH_TOKEN) headers.Authorization = `Bearer ${env.GH_TOKEN}`
    if (etag) headers['If-None-Match'] = etag
    const res = await doFetch(issuesEndpoint(repo), { headers })
    return { status: res.status, etag: res.headers.get('etag') || undefined }
  }
}

// The Docs tab's saved copy of a GitHub-only project (#565, electron/main/docs_saved.js): the same conditional GET, on the
// repo's recursive git tree. Sent once when the project is opened, never on a timer. A 304 is free; a 200's body is
// the new tree, with each file's blob sha, so the caller downloads only the docs that changed.
export const treeEndpoint = (repo) => `https://api.github.com/repos/${repo}/git/trees/HEAD?recursive=1`
export function createTreeProbe(env = process.env, doFetch = fetch) {
  return async (repo, etag) => {
    const headers = { Accept: 'application/vnd.github+json', 'User-Agent': 'marvin-dashboard-watch' }
    if (env.GH_TOKEN) headers.Authorization = `Bearer ${env.GH_TOKEN}`
    if (etag) headers['If-None-Match'] = etag
    const res = await doFetch(treeEndpoint(repo), { headers })
    const out = { status: res.status, etag: res.headers.get('etag') || undefined }
    if (res.status === 200) out.body = await res.json()
    return out
  }
}

export function startChangeWatch({ getRepos, probe, ping, intervalMs = 20_000, setIntervalFn = setInterval }) {
  const detector = createChangeDetector({ probe, onChange: (repo) => ping(repo) })
  let running = false
  const run = async () => {
    if (running) return // a slow tick must not stack
    running = true
    try {
      await detector.tick(getRepos())
    } finally {
      running = false
    }
  }
  run()
  return setIntervalFn(run, intervalMs)
}

// ---------------------------------------------------------------------------------------------------------------------
// Check watch (marvin#555, replacing #554's 90 s re-read of the whole PR list): GitHub checks starting or finishing is
// not an issue/PR update, so the probe above never sees it. While a PR's checks are running, ask GitHub about that one
// commit's checks with an ETag on the same ~20 s rhythm: a 304 is free against the rate limit, and only a 200 whose
// checks differ from what the cached PR list showed re-reads that repo's list. A commit stops being watched (its etag
// dropped) as soon as the list no longer shows it pending: its checks finished, the PR closed, or a push replaced it.

export const checkRunsEndpoint = (repo, sha) => `https://api.github.com/repos/${repo}/commits/${sha}/check-runs?per_page=100`
export const combinedStatusEndpoint = (repo, sha) => `https://api.github.com/repos/${repo}/commits/${sha}/status?per_page=100`

// What a commit's checks look like, as one comparable string, from either side: the PR list's statusCheckRollup
// (GraphQL, upper case) or the REST probe (lower case, mapped to the same shape). Order and case never matter.
export function checksDigest(rollup) {
  const runs = checkRuns((rollup || []).filter((c) => c && c.__typename === 'CheckRun'))
  return runs.map((r) => `${r.name}|${r.status}`).sort().join('\n')
}
// "EXPECTED" (required but never posted) exists only in GraphQL; REST never lists it, so it is left out of both sides.
export function statusesDigest(rollup) {
  return (rollup || [])
    .filter((c) => c && c.__typename === 'StatusContext' && String(c.state).toUpperCase() !== 'EXPECTED')
    .map((c) => `${c.context}|${String(c.state).toLowerCase()}`).sort().join('\n')
}

const fromRest = {
  'check-runs': (body) => checksDigest((body?.check_runs || []).map((r) => ({ __typename: 'CheckRun', name: r.name, status: String(r.status || '').toUpperCase(), conclusion: String(r.conclusion || '').toUpperCase() }))),
  status: (body) => statusesDigest((body?.statuses || []).map((s) => ({ __typename: 'StatusContext', context: s.context, state: String(s.state || '').toUpperCase() })))
}

// probe({kind: 'check-runs'|'status', repo, sha, etag}) -> {status, etag, digest}. heads: [{repo, sha, checkRuns, statuses}]
// where checkRuns/statuses are the list's digests (null = that kind is not in use on this PR, so it is not probed).
export function createCheckWatcher({ probe, onChange, now = Date.now }) {
  const watched = new Map() // `${kind}|${repo}@${sha}` -> { etag, checkedAt }

  async function tick(heads) {
    const wanted = new Map()
    for (const h of Array.isArray(heads) ? heads : []) {
      if (!h || !h.repo || !h.sha) continue
      for (const [kind, digest] of [['check-runs', h.checkRuns], ['status', h.statuses]]) {
        if (digest == null) continue
        const key = `${kind}|${h.repo}@${h.sha}`
        if (!wanted.has(key)) wanted.set(key, { kind, repo: h.repo, sha: h.sha, digest })
      }
    }
    for (const key of [...watched.keys()]) if (!wanted.has(key)) watched.delete(key)
    const changed = new Set()
    for (const [key, w] of wanted) {
      const known = watched.get(key) || {}
      let res
      try {
        res = await probe({ kind: w.kind, repo: w.repo, sha: w.sha, etag: known.etag })
      } catch {
        continue // offline / refused: keep the etag, and do not claim we looked
      }
      if (!res || (res.status !== 200 && res.status !== 304)) continue
      watched.set(key, { etag: (res.status === 200 && res.etag) || known.etag, checkedAt: now() })
      if (res.status === 200 && res.digest !== undefined && res.digest !== w.digest) changed.add(w.repo)
    }
    for (const repo of changed) onChange(repo)
  }

  // When GitHub was last asked about this commit's checks (any kind), in ms, or null.
  function checkedAt(repo, sha) {
    let at = null
    for (const kind of ['check-runs', 'status']) {
      const w = watched.get(`${kind}|${repo}@${sha}`)
      if (w?.checkedAt != null && (at == null || w.checkedAt > at)) at = w.checkedAt
    }
    return at
  }

  return { tick, checkedAt, size: () => watched.size }
}

// Real probe: the same authenticated conditional GET as createGithubProbe. A body is read only on a 200.
export function createCheckProbe(env = process.env, doFetch = fetch) {
  return async ({ kind, repo, sha, etag }) => {
    const headers = { Accept: 'application/vnd.github+json', 'User-Agent': 'marvin-dashboard-watch' }
    if (env.GH_TOKEN) headers.Authorization = `Bearer ${env.GH_TOKEN}`
    if (etag) headers['If-None-Match'] = etag
    const res = await doFetch(kind === 'status' ? combinedStatusEndpoint(repo, sha) : checkRunsEndpoint(repo, sha), { headers })
    const out = { status: res.status, etag: res.headers.get('etag') || undefined, digest: undefined }
    if (res.status === 200) {
      try {
        out.digest = (fromRest[kind] || fromRest['check-runs'])(await res.json())
      } catch {
        out.digest = undefined
      }
    }
    return out
  }
}

// Runs the watcher on an interval: a slow tick never stacks, nothing is asked while skip() says so (the GitHub gate is
// cooling down), and a failing getHeads only skips that tick.
export function startCheckWatch({ getHeads, probe, onChange, intervalMs = 20_000, setIntervalFn = setInterval, skip = () => false, now = Date.now }) {
  const watcher = createCheckWatcher({ probe, onChange, now })
  let running = false
  const run = async () => {
    if (running) return
    running = true
    try {
      if (skip()) return
      await watcher.tick(getHeads())
    } catch {
      // the watch must never die: try again next tick
    } finally {
      running = false
    }
  }
  run()
  const timer = setIntervalFn(run, intervalMs)
  timer?.unref?.()
  return { watcher, timer, run }
}
