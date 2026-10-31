// marvin#231: this is information now, not a rule. The merge queue (webhook-server/merge_order.js) decides each PR's turn
// and Approve is never refused for order; waitingOn is still listed for what it tells the owner about overlap.
// Merge order. Two open PRs that change the same file will conflict once the first lands, which is
// exactly what the merge gate then reports as REBASE_CONFLICT. So a PR waits on every OLDER open PR in
// its repo that shares a changed file with it. Derived from the PRs' own file lists each time, never stored.
// An older PR that cannot merge as it stands (it conflicts with main, or its ticket was sent back and is being rebuilt)
// is not waited on: waiting for it would hold every newer PR hostage to the rebuild queue (clarity-captions #62/#63/#64,
// 2026-10-06), and its rebuild lands on whatever main has by then. The same goes for an older PR stuck on its own
// blocker (`blocked`: no images, a vague ask, open decisions, failing checks): one PR missing screenshots held #378,
// #371 and #389 hostage on 2026-10-09 while it could never be approved itself. A draft is skipped too: GitHub won't
// merge it, so a parked or in-progress draft held a ready PR hostage (clarity #227 and #238 held #239, 2026-10-30).
export function waitingOn(prs, pr) {
  if (!Array.isArray(pr.files)) return []
  const mine = new Set(pr.files.map((f) => f.path))
  return prs
    .filter((o) => o.repo === pr.repo && o.number < pr.number && Array.isArray(o.files) && o.mergeable !== 'CONFLICTING' && !o.isDraft && !o.sentBack && !o.blocked)
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

// The code says which refusal it was, so it can be recorded (#215, approve_guard.js).
const refused = (code, message) => Object.assign(new Error(message), { code })

// What the Approve click still refuses (marvin#231: everything about ORDER is the merge queue's now). A PR aimed at a
// side branch that is not another open PR's head can never reach main, so it is refused, as before. A stacked PR (its
// base is an open PR's branch) and a PR that shares files with an older one are no longer refused: Approve queues
// them, and the queue merges the base first and rebases and retests each one on the main of its turn (merge_order.js).
export function assertInOrder(prs, url) {
  const pr = prs.find((p) => p.url === url)
  if (!pr) return
  const bp = baseProblem(prs, pr)
  if (bp && !bp.parent) {
    throw refused('WRONG_BASE', `This PR targets "${bp.base}", not ${bp.expected}, so merging it would not put the work on ${bp.expected}. Change its base to ${bp.expected} on GitHub first.`)
  }
}
