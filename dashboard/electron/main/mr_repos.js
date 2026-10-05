// MR Review across projects. The list spans every registered board repo; the
// merge gate (webhook-server/merge.js) is built in for marvin and profile-driven for other projects:
// they get Approve/Deny only when their profile opts in (merge_from_dashboard).
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
