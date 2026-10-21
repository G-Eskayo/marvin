// MR Review across projects. The list spans every registered board repo; the
// merge gate (webhook-server/merge.js) is built in for marvin and profile-driven for other projects:
// they get Approve/Deny only when their profile opts in (merge_from_dashboard).
import { ciState } from '../../webhook-server/ci_status.js'

export const MARVIN_REPO = 'G-Eskayo/marvin'

export const prKey = (repo, number) => `${repo}#${number}`
// marvin always (its gate is built in); another project only when its profile opted in (profiles.js).
export const canMergeFromDashboard = (repo, mergeable = new Set()) => repo === MARVIN_REPO || mergeable.has(repo)

// Seen-tracking used to store bare PR numbers (marvin only). Keep reading them, as marvin's.
export const normalizeSeen = (seen) => seen.map((x) => (typeof x === 'number' ? prKey(MARVIN_REPO, x) : x))

export async function listOpenPrsAcrossRepos(repos, ghList) {
  const all = [MARVIN_REPO, ...repos.filter((r) => r !== MARVIN_REPO)]
  const prs = []
  const errors = []
  for (const repo of all) {
    try {
      for (const pr of await ghList(repo)) prs.push({ ...pr, repo })
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
  const fields = light ? 'number,title,url' : 'number,title,url,body,files,baseRefName,headRefName,mergeable,statusCheckRollup'
  return ['pr', 'list', '--repo', repo, '--state', 'open', '--limit', '200', '--json', fields]
}

// How soon to re-read a repo's open-PR list whose checks are still running, or undefined when none are. The change
// watch (gh_watch.js) only notices issue/PR updates; GitHub checks finishing is not one, so a list read right after a
// push kept "Waiting for GitHub checks" until the 30-minute safety refresh (clarity-captions#143, 2026-10-21). Costs
// one list read per repo per interval, and only while that repo has checks running and MR Review is open.
export const PENDING_CHECKS_TTL_MS = 90_000
export function pendingChecksTtl(prs) {
  if (!Array.isArray(prs)) return undefined
  return prs.some((p) => p && Array.isArray(p.statusCheckRollup) && ciState(p.statusCheckRollup).state === 'pending') ? PENDING_CHECKS_TTL_MS : undefined
}
