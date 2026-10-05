// Merge order. Two open PRs that change the same file will conflict once the first lands, which is
// exactly what the merge gate then reports as REBASE_CONFLICT. So a PR waits on every OLDER open PR in
// its repo that shares a changed file with it. Derived from the PRs' own file lists each time, never stored.
export function waitingOn(prs, pr) {
  if (!Array.isArray(pr.files)) return []
  const mine = new Set(pr.files.map((f) => f.path))
  return prs
    .filter((o) => o.repo === pr.repo && o.number < pr.number && Array.isArray(o.files))
    .map((o) => ({ number: o.number, title: o.title, url: o.url, shared: o.files.map((f) => f.path).filter((p) => mine.has(p)).sort() }))
    .filter((o) => o.shared.length)
    .sort((a, b) => a.number - b.number)
}

// A PR must target the project's base branch. One aimed at a side branch gets "merged" there by GitHub and
// never reaches main (finance-os #8). If that side branch is another open PR's head, this one is stacked on it.
export function baseProblem(prs, pr, baseBranch = 'main') {
  if (!pr.baseRefName || pr.baseRefName === baseBranch) return null
  const parent = prs.find((o) => o.repo === pr.repo && o.headRefName === pr.baseRefName && o.number !== pr.number)
  return { base: pr.baseRefName, expected: baseBranch, parent: parent ? { number: parent.number, title: parent.title, url: parent.url } : null }
}

// The same rule, enforced where the merge is started so no stale screen can skip it.
export function assertInOrder(prs, url) {
  const pr = prs.find((p) => p.url === url)
  if (!pr) return
  const bp = baseProblem(prs, pr)
  if (bp) {
    throw new Error(`This PR targets "${bp.base}", not ${bp.expected}, so merging it would not put the work on ${bp.expected}.` +
      (bp.parent ? ` It is stacked on #${bp.parent.number}: merge #${bp.parent.number} first, then change this PR's base to ${bp.expected}.` : ` Change its base to ${bp.expected} on GitHub first.`))
  }
  const w = waitingOn(prs, pr)
  if (w.length) {
    const first = w.map((x) => `#${x.number}`).join(', ')
    const why = w.map((x) => `#${x.number} shares ${x.shared.slice(0, 2).join(', ')}`).join('; ')
    throw new Error(`Merge ${first} first: this PR changes the same files (${why}), so merging it now would conflict.`)
  }
}
