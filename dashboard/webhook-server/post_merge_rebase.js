import { parseTicketRef } from '../electron/main/mr_review.js'
import { recordStage } from './ticket_stages.js'
import { writeRebaseStatus } from './rebase_status.js'

// After every merge, rebase the repo's other open PRs onto the new base branch, by code, no LLM (#225). Before this,
// nothing re-integrated a PR until someone pressed Approve, so a conflict surfaced at the worst moment, and the
// pipeline's scan then sent every conflicting ticket back for a full rebuild. Now a PR that rebases clean is pushed
// (so its Approve skips the gate's rebase), and one that conflicts or goes red is left alone with the reason recorded
// for MR Review. What happens to a real conflict next is #230's business.
//
// `rebase(headRefName)` is the gate's own rebaseAndRetest, bound to the repo: scratch worktree, retest, push only
// when green. One PR at a time: each one is tested against the same main.

export function conflictFiles(text) {
  return [...String(text).matchAll(/CONFLICT \([^)]*\): Merge conflict in (\S+)/g)].map((m) => m[1])
}

const prNumber = (url) => Number(String(url).match(/\/pull\/(\d+)/)?.[1] ?? 0)

export async function rebaseOpenPrs({ repo, mergedPrUrl, base = 'main', exec, rebase, recordStageFn = recordStage, writeStatus = writeRebaseStatus, now = () => new Date() }) {
  let prs
  try {
    const { stdout } = await exec('gh', ['pr', 'list', '--repo', repo, '--state', 'open', '--limit', '100',
      '--json', 'number,url,headRefName,baseRefName,isCrossRepository,body'])
    prs = JSON.parse(stdout)
    if (!Array.isArray(prs)) return []
  } catch {
    return []
  }
  const after = prNumber(mergedPrUrl)
  const entries = []
  // A PR stacked on the one just merged still targets that PR's branch, and GitHub only retargets it when the branch
  // is deleted (merges here keep it). Left alone it can never reach main: merged there, its work silently misses main
  // and its ticket never closes. So move it onto the base branch first, then it is rebased like any other.
  let mergedHead = null
  try {
    const { stdout } = await exec('gh', ['pr', 'view', mergedPrUrl, '--json', 'headRefName'])
    mergedHead = JSON.parse(stdout).headRefName || null
  } catch { /* no head known: nothing to retarget */ }
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
      const res = await rebase(pr.headRefName)
      reason = res.reason || ''
      files = res.ok ? [] : conflictFiles(reason)
      state = res.ok ? 'clean' : /^Rebase onto main failed/i.test(reason) ? 'conflict' : 'tests_failed'
    } catch (e) {
      state = 'error'
      reason = String(e?.message || e)
    }
    entries.push({ url: pr.url, pr: pr.number, state, files, after, at: now().toISOString(), reason: reason.slice(0, 300),
      ...(retargeted.has(pr.url) ? { retargetedFrom: retargeted.get(pr.url) } : {}) })
    const ref = parseTicketRef(pr.body || '')
    if (ref !== null) {
      const detail = state === 'clean' ? `rebased onto ${base} after PR #${after} merged`
        : state === 'conflict' ? `REBASE_CONFLICT after PR #${after} merged: ${files.join(', ')}`
        : state === 'tests_failed' ? `tests fail after rebasing onto ${base} (PR #${after} merged)`
        : `rebase after PR #${after} merged errored: ${reason.slice(0, 120)}`
      try { recordStageFn(Number(ref), 'gate', state === 'clean' ? 'passed' : 'failed', detail, { repo }) } catch { /* fail-soft */ }
    }
  }
  try { writeStatus(entries) } catch { /* fail-soft */ }
  return entries
}
