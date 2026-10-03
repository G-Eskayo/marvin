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
