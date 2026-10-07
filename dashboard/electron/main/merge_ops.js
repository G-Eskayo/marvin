// What each PR's Approve & Merge is doing right now, held in the main process so it survives the
// renderer unmounting (navigating away used to reset the button to "Approve & Merge" mid-merge).
// Failures and re-engagements are kept until the next attempt so the message is still there on return.
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
    start(url, now = Date.now()) {
      if (live(url, now)?.state === 'merging') return false
      ops.set(url, { state: 'merging', since: now })
      return true
    },
    finish(url, result) {
      if (result?.reengaged) ops.set(url, { state: 'reengaged', reason: result.reason })
      else ops.delete(url)
    },
    fail(url, reason) { ops.set(url, { state: 'error', reason }) },
    cancel(url) { ops.delete(url) },
    get(url, now = Date.now()) { return live(url, now) || { state: 'idle' } }
  }
}
