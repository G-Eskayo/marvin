// What each PR's Approve & Merge is doing right now, held in the main process so it survives the
// renderer unmounting (navigating away used to reset the button to "Approve & Merge" mid-merge).
// Failures and re-engagements are kept until the next attempt so the message is still there on return.
export function createMergeOps() {
  const ops = new Map()
  return {
    start(url) {
      if (ops.get(url)?.state === 'merging') return false
      ops.set(url, { state: 'merging', since: Date.now() })
      return true
    },
    finish(url, result) {
      if (result?.reengaged) ops.set(url, { state: 'reengaged', reason: result.reason })
      else ops.delete(url)
    },
    fail(url, reason) { ops.set(url, { state: 'error', reason }) },
    cancel(url) { ops.delete(url) },
    get(url) { return ops.get(url) || { state: 'idle' } }
  }
}
