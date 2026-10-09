// The safety net for stacked PRs (#312, 2026-10-09). A PR built on another PR targets that PR's branch; when the
// parent merges, the merge server moves it onto main (webhook-server/post_merge_rebase.js). That step can be missed:
// it failed silently on every merge until 2026-10-09, and a parent merged on GitHub's website never runs it. A PR left
// targeting a merged branch can never be approved (pr_order.js refuses WRONG_BASE). So each MR Review refresh checks:
// an open PR whose base branch no open PR owns, and whose parent PR MERGED, is moved onto main. A parent closed without
// merging is left alone (moving would drag its unmerged work along) and keeps showing the WRONG_BASE message.
const RECHECK_MS = 5 * 60_000

export function orphanedStacks(prs, base = 'main') {
  const heads = new Set((prs || []).map((p) => `${p.repo}|${p.headRefName}`))
  return (prs || []).filter((p) => p.baseRefName && p.baseRefName !== base && !heads.has(`${p.repo}|${p.baseRefName}`))
}

export function createStackRetarget({ gh, base = 'main', onMoved = () => {}, log = (m) => console.error(m), now = Date.now }) {
  const lastAsked = new Map() // pr url -> when GitHub was last asked about its parent
  return {
    async check(prs) {
      const moved = []
      for (const p of orphanedStacks(prs, base)) {
        if (now() - (lastAsked.get(p.url) ?? -Infinity) < RECHECK_MS) continue
        lastAsked.set(p.url, now())
        try {
          const parent = JSON.parse(await gh(['pr', 'list', '--repo', p.repo, '--state', 'merged', '--head', p.baseRefName, '--limit', '1', '--json', 'number']))[0]
          if (!parent) continue
          await gh(['pr', 'edit', p.url, '--base', base])
          moved.push({ repo: p.repo, number: p.number, from: p.baseRefName, parent: parent.number })
        } catch (e) {
          log(`[stack-retarget] PR #${p.number} (${p.repo}) still targets ${p.baseRefName}: ${String(e?.message || e).slice(0, 200)}`)
        }
      }
      if (moved.length) onMoved(moved)
      return moved
    }
  }
}
