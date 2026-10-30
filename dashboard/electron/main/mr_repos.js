// MR Review across projects. The list spans every registered board repo; the
// merge gate (webhook-server/merge.js) is built in for marvin and profile-driven for other projects:
// they get Approve/Deny only when their profile opts in (merge_from_dashboard).
import { ciState } from '../../webhook-server/ci_status.js'
import { checksDigest, statusesDigest } from '../../webhook-server/gh_watch.js'

export const MARVIN_REPO = 'G-Eskayo/marvin'

export const prKey = (repo, number) => `${repo}#${number}`
// marvin always (its gate is built in); another project only when its profile opted in (profiles.js).
export const canMergeFromDashboard = (repo, mergeable = new Set()) => repo === MARVIN_REPO || mergeable.has(repo)

// Seen-tracking used to store bare PR numbers (marvin only). Keep reading them, as marvin's.
export const normalizeSeen = (seen) => seen.map((x) => (typeof x === 'number' ? prKey(MARVIN_REPO, x) : x))

// listedAt(repo): when that repo's list was last read from GitHub (ms), for MR Review's "Last checked" (marvin#555).
export async function listOpenPrsAcrossRepos(repos, ghList, { listedAt = null } = {}) {
  const all = [MARVIN_REPO, ...repos.filter((r) => r !== MARVIN_REPO)]
  const prs = []
  const errors = []
  const readAt = (repo) => {
    try {
      const at = listedAt?.(repo)
      return Number.isFinite(at) ? at : null
    } catch {
      return null
    }
  }
  for (const repo of all) {
    try {
      const list = await ghList(repo)
      const at = readAt(repo)
      for (const pr of list) prs.push({ ...pr, repo, listedAt: at })
    } catch (err) {
      // One project's outage must not hide every other project's MRs.
      errors.push({ repo, message: String(err.message || err) })
    }
  }
  return { prs, errors }
}

// Derive the repo from the PR url itself rather than trusting a flag the renderer sends.
export function repoFromPrUrl(url) {
  const m = typeof url === 'string' ? url.match(/^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/pull\/\d+/) : null
  return m ? m[1] : null
}

// What `gh pr list` is asked for. GraphQL cost grows with every nested field, and `files` is the expensive
// one, so the status dot (polled every minute; it only counts PRs) gets the light form -- the full form
// (bodies for the evidence schema, files and branch names for merge order) is for the list itself.
export function prListArgs(repo, { light = false } = {}) {
  const fields = light ? 'number,title,url' : 'number,title,url,isDraft,body,files,baseRefName,headRefName,headRefOid,mergeable,statusCheckRollup'
  return ['pr', 'list', '--repo', repo, '--state', 'open', '--limit', '200', '--json', fields]
}

// The commits whose checks are still running, from a repo's cached PR list: what the check watch (gh_watch.js,
// marvin#555) asks GitHub about every ~20 s with an ETag. One entry per commit, carrying what the list showed, so only a
// real difference re-reads the list. A light list (no rollup, no head commit) has nothing to watch.
export function pendingCheckHeads(repo, prs) {
  if (!Array.isArray(prs)) return []
  const heads = new Map()
  for (const p of prs) {
    if (!p || !p.headRefOid || !Array.isArray(p.statusCheckRollup) || heads.has(p.headRefOid)) continue
    if (ciState(p.statusCheckRollup).state !== 'pending') continue
    const has = (t) => p.statusCheckRollup.some((c) => c && c.__typename === t)
    heads.set(p.headRefOid, {
      repo,
      sha: p.headRefOid,
      checkRuns: has('CheckRun') ? checksDigest(p.statusCheckRollup) : null,
      statuses: has('StatusContext') ? statusesDigest(p.statusCheckRollup) : null
    })
  }
  return [...heads.values()]
}
