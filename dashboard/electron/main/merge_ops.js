// What each PR's Approve & Merge is doing right now, held in the main process so it survives the
// renderer unmounting (navigating away used to reset the button to "Approve & Merge" mid-merge).
// Failures and re-engagements are kept until the next attempt so the message is still there on return -- but only for
// the commit they happened on: once the PR has a newer head, the old failure no longer describes it (Gil, 2026-10-21).
export function createMergeOps({ maxMergingMs = 45 * 60_000 } = {}) {
  const ops = new Map()
  // A merge that never reports back (a hung gate) must not read "Merging…" forever: past the limit it is an error,
  // and a new attempt may start.
  const live = (url, now) => {
    const o = ops.get(url)
    if (o && o.state === 'merging' && now - o.since > maxMergingMs) {
      const expired = { state: 'error', reason: 'The merge did not finish within the time limit and was given up on. Approve again to retry.' }
      ops.set(url, expired)
      return expired
    }
    return o
  }
  return {
    start(url, now = Date.now(), head = null) {
      if (live(url, now)?.state === 'merging') return false
      ops.set(url, { state: 'merging', since: now, head })
      return true
    },
    finish(url, result) {
      if (result?.reengaged) ops.set(url, { state: 'reengaged', reason: result.reason, head: ops.get(url)?.head ?? null })
      else ops.delete(url)
    },
    fail(url, reason) { ops.set(url, { state: 'error', reason, head: ops.get(url)?.head ?? null }) },
    cancel(url) { ops.delete(url) },
    get(url, now = Date.now(), head = null) {
      const o = live(url, now)
      if (!o) return { state: 'idle' }
      // A finished attempt on an older commit says nothing about the new one. Unknown heads keep it: never hide a failure.
      if (o.state !== 'merging' && head && o.head && head !== o.head) return { state: 'idle' }
      return o
    }
  }
}
