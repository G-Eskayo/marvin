import { parseTicketRef } from '../electron/main/mr_review.js'
import { recordStage } from './ticket_stages.js'
import { writeRebaseStatus } from './rebase_status.js'

// After every merge (#225, reworked 2026-10-09 by the overlap rule): PRs stacked on the merged one are moved onto the
// base branch, and every other open PR gets a conflict check (git merge-tree: no checkout, no tests, no push, seconds),
// so MR Review shows "conflicts with main" before anyone presses Approve. It used to rebase and fully retest every open
// PR after every merge, one at a time, and force-push each: ~8 test runs per merge, all stale at the next merge. The
// one retest that matters happens at Approve, and only when main changed files the PR also changes (merge.js).
//
// `check(headRefName)` is merge.js conflictsWithBase bound to the repo: { conflict, files }.

const prNumber = (url) => Number(String(url).match(/\/pull\/(\d+)/)?.[1] ?? 0)

export async function checkOpenPrs({ repo, mergedPrUrl, base = 'main', exec, check, recordStageFn = recordStage, writeStatus = writeRebaseStatus, now = () => new Date(), log = (m) => console.error(m) }) {
  const after = prNumber(mergedPrUrl)
  let prs
  try {
    const out = await exec('gh', ['pr', 'list', '--repo', repo, '--state', 'open', '--limit', '100',
      '--json', 'number,url,headRefName,baseRefName,isCrossRepository,body'])
    prs = JSON.parse(out?.stdout ?? '')
    if (!Array.isArray(prs)) throw new Error('the PR list was not a list')
  } catch (e) {
    // Said out loud: this failed silently on every merge until 2026-10-09 (the exec returned no output), so stacked
    // PRs were never moved onto main. The MR Review safety net (stack_retarget.js) catches what this misses.
    const reason = `After PR #${after} merged, could not list the open PRs to check them: ${String(e?.message || e)}`.slice(0, 300)
    log(`[post-merge] ${repo}: ${reason}`)
    const failed = [{ url: mergedPrUrl, pr: after, state: 'error', files: [], after, at: now().toISOString(), reason }]
    try { writeStatus(failed) } catch { /* fail-soft */ }
    return failed
  }
  const entries = []
  // A PR stacked on the one just merged still targets that PR's branch, and GitHub only retargets it when the branch
  // is deleted (merges here keep it). Left alone it can never reach main: merged there, its work silently misses main
  // and its ticket never closes. So move it onto the base branch first, then it is checked like any other.
  let mergedHead = null
  try {
    const out = await exec('gh', ['pr', 'view', mergedPrUrl, '--json', 'headRefName'])
    mergedHead = JSON.parse(out?.stdout ?? '').headRefName || null
  } catch (e) {
    log(`[post-merge] ${repo}: could not read PR #${after}'s branch, so PRs stacked on it were not moved onto ${base}: ${String(e?.message || e).slice(0, 200)}`)
  }
  const retargeted = new Map()
  for (const pr of prs.filter((p) => mergedHead && p.baseRefName === mergedHead && !p.isCrossRepository)) {
    try {
      await exec('gh', ['pr', 'edit', pr.url, '--base', base])
      retargeted.set(pr.url, pr.baseRefName)
      pr.baseRefName = base
    } catch (e) {
      entries.push({ url: pr.url, pr: pr.number, state: 'error', files: [], after, at: now().toISOString(),
        reason: `PR #${after} merged but couldn't move it onto ${base}: ${String(e?.message || e)}`.slice(0, 300) })
    }
  }
  for (const pr of prs.filter((p) => p.url !== mergedPrUrl && p.baseRefName === base && !p.isCrossRepository)) {
    let state, files = [], reason = ''
    try {
      const res = await check(pr.headRefName)
      files = res.files || []
      state = res.conflict ? 'conflict' : 'clean'
      reason = res.conflict ? `conflicts with ${base} after PR #${after} merged: ${files.join(', ')}` : ''
    } catch (e) {
      state = 'error'
      reason = String(e?.message || e)
    }
    entries.push({ url: pr.url, pr: pr.number, state, files, after, at: now().toISOString(), reason: reason.slice(0, 300),
      ...(retargeted.has(pr.url) ? { retargetedFrom: retargeted.get(pr.url) } : {}) })
    // Only a conflict goes on the ticket's timeline: "still merges" is not a test result, so it is not a gate pass.
    const ref = parseTicketRef(pr.body || '')
    if (ref !== null && state === 'conflict') {
      try { recordStageFn(Number(ref), 'gate', 'failed', `REBASE_CONFLICT after PR #${after} merged: ${files.join(', ')}`, { repo }) } catch { /* fail-soft */ }
    }
  }
  try { writeStatus(entries) } catch { /* fail-soft */ }
  return entries
}
