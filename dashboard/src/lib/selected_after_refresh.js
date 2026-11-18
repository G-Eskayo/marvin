// Decide what to do when a selected PR disappears from the refreshed list.
// Returns 'open' (update to fresh), 'check' (need to call historyDetail),
// 'unknown' (can't tell), or 'none' (PR is gone).
export function selectedAfterRefresh(cur, list, fetchErrors) {
  if (!cur) return 'none'

  // PR is still in the list: use the fresh data
  const found = list.find((p) => p.key === cur.key)
  if (found) return 'open'

  // PR is already marked as read-only (closed/merged): don't check again
  if (cur.readOnly) return 'none'

  // List fetch status unknown: can't make any decision
  if (fetchErrors === null || fetchErrors === undefined) return 'unknown'

  // List succeeded but has errors: check if any errors are for this PR's repo
  if (fetchErrors?.length) {
    const curRepo = cur.repo || extractRepoFromUrl(cur.url)
    const hasErrorForRepo = fetchErrors.some((e) => e.repo === curRepo)
    if (hasErrorForRepo) return 'unknown'
  }

  // List succeeded, PR is gone, and we have time to check: fetch it
  if (cur.url) return 'check'

  // No URL to check with: PR is gone
  return 'none'
}

function extractRepoFromUrl(url) {
  if (!url) return null
  // Extract org/repo from https://github.com/org/repo/pull/123
  const match = url.match(/github\.com\/([^/]+\/[^/]+)\//)
  return match ? match[1] : null
}
