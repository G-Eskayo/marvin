import { parseDecisions } from '../../webhook-server/decisions.js'

// Local-first actions (CONTEXT.md "Dashboard actions render their true result locally at once, and confirm in the
// background", Gil 2026-10-21: "Clicks render the true result instantly and confirm in the background" and "I want that
// to be accurate, not just a show"). When MR Review writes something to GitHub it already knows what it wrote, so:
//
//   1. the result is applied to the dashboard's memory of GitHub (github_state.js patch) at once, from GitHub's own
//      answer to the write, never a guess, and the screen reads it from there;
//   2. GitHub is asked about that one PR or ticket, once, in the background, with a conditional request (the gh_watch.js
//      ETag pattern: a 304 is free against the rate limit);
//   3. if GitHub has something else, the view takes GitHub's version and onCorrected says so in plain words.
//
// No timers: the confirm runs once, right after the write. Later changes arrive the usual way (change watch pings).
// Each PR/ticket has a version: a confirm applies only if no newer local write happened while it was on its way, so a
// slow answer can never put an older state over a newer one. Writes to one PR run one at a time (serialize), so a
// second click's read sees the first click's write. O(1) per action; never a re-list of every repo.

// owner/name; never a path step ('.' or '..'), which would turn the URL into a different endpoint.
const REPO_RE = /^(?!\.\.?\/)[A-Za-z0-9_.-]+\/(?!\.\.?$)[A-Za-z0-9_.-]+$/

export function createLocalFirst({ state, readIssue, onCorrected = () => {} }) {
  const versions = new Map() // `${repo}#${number}` -> version of the latest local write
  const chains = new Map()   // same key -> tail of its write queue
  const keyOf = (repo, number) => `${repo}#${Number(number)}`
  const bump = (repo, number) => {
    const k = keyOf(repo, number)
    const v = (versions.get(k) || 0) + 1
    versions.set(k, v)
    return v
  }
  const current = (repo, number, ver) => (versions.get(keyOf(repo, number)) || 0) === ver
  const prUrl = (repo, number) => `https://github.com/${repo}/pull/${Number(number)}`

  const mapPr = (repo, number, fn) => state.patch('prs', repo, (list) => (Array.isArray(list) ? list.map((p) => (p && p.number === Number(number) ? fn(p) : p)) : list))
  // The board's copy (tickets, and its own PR list): a ticket's labels decide "sent back", its body its Decisions.
  const mapTicket = (repo, number, fn, { prs = false } = {}) => state.patch('board', repo, (data) => {
    if (!data || !Array.isArray(data.issues)) return data
    const one = (x) => (x && x.number === Number(number) ? fn(x) : x)
    return { ...data, issues: data.issues.map(one), ...(prs && Array.isArray(data.prs) ? { prs: data.prs.map(one) } : {}) }
  })
  const withLabel = (issue, label, present) => {
    const rest = (issue.labels || []).filter((l) => (typeof l === 'string' ? l : l?.name) !== label)
    return { ...issue, labels: present ? [...rest, { name: label }] : rest }
  }

  // Asks GitHub once; null when it could not say (offline, refused, garbled) or a newer local write superseded it.
  async function ask(repo, number, ver, etag) {
    let r
    try {
      r = await readIssue(repo, Number(number), etag)
    } catch {
      return { status: 'unconfirmed' }
    }
    if (!current(repo, number, ver)) return { status: 'superseded' }
    if (r?.status === 304) return { status: 'confirmed' }
    if (r?.status !== 200 || !r.issue || typeof r.issue !== 'object') return { status: 'unconfirmed' }
    return { status: 'read', issue: r.issue }
  }
  const tell = (repo, number, url, message) => {
    try { onCorrected({ repo, number: Number(number), url, message }) } catch { /* a listener's mistake never breaks the action */ }
  }

  return {
    serialize(key, fn) {
      const prev = chains.get(key) || Promise.resolve()
      const run = prev.then(fn, fn)
      const tail = run.catch(() => {})
      chains.set(key, tail)
      tail.then(() => { if (chains.get(key) === tail) chains.delete(key) })
      return run
    },

    // The PR's description, as GitHub answered the write.
    setPrBody(repo, number, body) {
      const ver = bump(repo, number)
      mapPr(repo, number, (p) => ({ ...p, body }))
      mapTicket(repo, number, (i) => ({ ...i, body }), { prs: true })
      return ver
    },
    async confirmBody(repo, number, { ver, etag, body }) {
      const r = await ask(repo, number, ver, etag)
      if (r.status !== 'read') return r
      const theirs = r.issue.body ?? ''
      if (theirs === body) return { status: 'confirmed' }
      mapPr(repo, number, (p) => ({ ...p, body: theirs }))
      mapTicket(repo, number, (i) => ({ ...i, body: theirs }), { prs: true })
      const problem = decisionsDisagreement(body, theirs)
      if (!problem) return { status: 'updated' }
      tell(repo, number, prUrl(repo, number), problem)
      return { status: 'corrected', message: problem }
    },

    // A merged or dropped PR leaves the open list at once.
    removePr(repo, number) {
      const ver = bump(repo, number)
      const drop = (list) => (Array.isArray(list) ? list.filter((p) => p?.number !== Number(number)) : list)
      state.patch('prs', repo, drop)
      state.patch('prs-light', repo, drop)
      return ver
    },
    async confirmClosed(repo, number, { ver, url, verb = 'closed' }) {
      const r = await ask(repo, number, ver)
      if (r.status !== 'read') return r
      if (String(r.issue.state).toLowerCase() === 'closed') return { status: 'confirmed' }
      state.changed(repo) // put it back: this repo is re-read on the next look, no other
      const message = `GitHub still shows #${Number(number)} open, although it was ${verb} from here. The list shows what GitHub has.`
      tell(repo, number, url || prUrl(repo, number), message)
      return { status: 'corrected', message }
    },

    // A ticket's label (sent back for rework, or cleared), as the write left it.
    setTicketLabel(repo, number, label, present) {
      const ver = bump(repo, number)
      mapTicket(repo, number, (i) => withLabel(i, label, present))
      return ver
    },
    async confirmLabel(repo, number, { ver, label, present, url }) {
      const r = await ask(repo, number, ver)
      if (r.status !== 'read') return r
      if (!sentBackDisagreement(r.issue, label, present)) return { status: 'confirmed' }
      mapTicket(repo, number, (i) => withLabel(i, label, !present))
      const message = present
        ? `GitHub does not show ticket #${Number(number)} as sent back ("${label}" is missing). The card shows what GitHub has.`
        : `GitHub still shows ticket #${Number(number)} as sent back ("${label}" is still on it). The card shows what GitHub has.`
      tell(repo, number, url || null, message)
      return { status: 'corrected', message }
    }
  }
}

export function sentBackDisagreement(issue, label, present) {
  const has = (issue?.labels || []).some((l) => (typeof l === 'string' ? l : l?.name) === label)
  return has !== present
}

const answerOf = (q) => (q.kind === 'text' ? (q.answer || '').trim() : q.options.filter((o) => o.checked).map((o) => o.label).join(', '))

// What GitHub's description says differently from the one written, about the Decisions only, in plain words; null when
// the answers agree (other text changing is not a disagreement about what Gil chose).
export function decisionsDisagreement(written, theirs) {
  try {
    const mine = parseDecisions(String(written ?? ''))
    const got = parseDecisions(String(theirs ?? ''))
    if (!mine.present) return null
    if (!got.present) return 'GitHub\'s description no longer has a Decisions section, so your answers are not there. The card shows what GitHub has.'
    const byId = new Map(got.questions.map((q) => [q.id, q]))
    const diffs = []
    for (const q of mine.questions) {
      const g = byId.get(q.id)
      const a = answerOf(q)
      const b = g ? answerOf(g) : ''
      if (a !== b) diffs.push(`"${q.question}": GitHub shows ${b ? `"${b}"` : 'no answer'}${a ? `, not "${a}"` : ''}`)
    }
    if (!diffs.length) return null
    return `GitHub has different answers than the ones you just sent. ${diffs.join('; ')}. The card shows what GitHub has.`
  } catch {
    return null
  }
}

// Overlapping callers share one read; a caller that arrives after a local write gets a new one (built from memory, so
// it is cheap), never an answer that predates the write. A failed read is not remembered.
export function coalesce(fn, version = () => 0) {
  let cur = null
  return () => {
    const v = version()
    if (cur && cur.v === v) return cur.p
    const p = new Promise((resolve) => resolve(fn())) // starts now, so it reads the state as of this call
    const mine = { v, p }
    cur = mine
    p.then(() => { if (cur === mine) cur = null }, () => { if (cur === mine) cur = null })
    return p
  }
}

// Where GitHub's REST API is. MARVIN_GITHUB_API points a sandbox (the evidence capture's fake GitHub) elsewhere, but
// only at this machine: the shared token rides on these requests, so it can never be sent to another host.
export function apiBase(env = process.env) {
  const v = env.MARVIN_GITHUB_API
  if (!v) return 'https://api.github.com'
  try {
    const u = new URL(v)
    if (u.protocol === 'http:' && (u.hostname === '127.0.0.1' || u.hostname === 'localhost')) return u.origin
  } catch { /* not a URL */ }
  return 'https://api.github.com'
}

const ghHeaders = (env, etag) => {
  const headers = { Accept: 'application/vnd.github+json', 'User-Agent': 'marvin-dashboard-local-first' }
  if (env.GH_TOKEN) headers.Authorization = `Bearer ${env.GH_TOKEN}`
  if (etag) headers['If-None-Match'] = etag
  return headers
}

// One conditional GET of an issue or PR (PRs are issues): body, state, labels. Same request shape as gh_watch.js's
// createGithubProbe, with the shared token path.js adopts. A 304 is free and carries nothing.
export function createIssueReader(env = process.env, doFetch = fetch) {
  return async (repo, number, etag) => {
    if (!REPO_RE.test(String(repo || ''))) throw new Error(`not a repository: ${repo}`)
    const n = Number(number)
    if (!Number.isInteger(n) || n <= 0) throw new Error(`not an issue or PR number: ${number}`)
    const res = await doFetch(`${apiBase(env)}/repos/${repo}/issues/${n}`, { headers: ghHeaders(env, etag), signal: AbortSignal.timeout(10_000) })
    const tag = res.headers.get('etag') || undefined
    if (res.status === 304) return { status: 304, etag: tag ?? etag }
    if (res.status !== 200) throw new Error(`GitHub answered ${res.status} for ${repo}#${n}`)
    return { status: 200, etag: tag, issue: await res.json() }
  }
}

// Approve's freshness check (P5): is the remembered open-PR list of this one repo still what GitHub has? One
// conditional GET of the repo's open pulls: a 304 against an etag that matched the remembered list is free and means
// fresh; a 200 is compared by number, head commit and base branch. Anything doubtful (offline, a second page, an etag
// that never matched) is stale, which re-reads that one repo -- never a pass on faith, never all 13 repos.
export function createRepoHeadCheck(env = process.env, doFetch = fetch) {
  const matched = new Map() // repo -> etag of a GitHub answer that equalled the remembered list
  const sig = (list) => list.map((p) => `${p.number}@${p.sha}>${p.base}`).sort().join(',')
  return async (repo, cachedPrs) => {
    if (!REPO_RE.test(String(repo || ''))) return { fresh: false }
    const mine = sig((cachedPrs || []).map((p) => ({ number: p.number, sha: p.headRefOid, base: p.baseRefName })))
    try {
      const res = await doFetch(`${apiBase(env)}/repos/${repo}/pulls?state=open&per_page=100`, { headers: ghHeaders(env, matched.get(repo)?.etag), signal: AbortSignal.timeout(10_000) })
      if (res.status === 304) return { fresh: matched.get(repo)?.sig === mine }
      if (res.status !== 200) return { fresh: false }
      const pulls = await res.json()
      if (!Array.isArray(pulls) || pulls.length >= 100) return { fresh: false }
      const theirs = sig(pulls.map((p) => ({ number: p.number, sha: p.head?.sha, base: p.base?.ref })))
      const etag = res.headers.get('etag')
      if (theirs === mine && etag) matched.set(repo, { etag, sig: mine })
      else matched.delete(repo)
      return { fresh: theirs === mine }
    } catch {
      return { fresh: false }
    }
  }
}
