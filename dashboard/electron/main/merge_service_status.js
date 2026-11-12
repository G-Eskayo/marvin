// Tracks reachability of the merge service (Mini's webhook) with hysteresis:
// instant clear on successful read, debounced latch when unreachable to avoid
// flapping from transient network glitches. Used by MR Review to show a banner
// when approvals are queued (reachable state unknown until the first read completes).
export function createMergeServiceTracker({ cacheMs = 30_000, now = Date.now } = {}) {
  let lastReachable = null
  let firstUnreachableAt = null
  let cachedDown = false

  return {
    report(reached) {
      const at = now()
      if (reached) {
        lastReachable = at
        firstUnreachableAt = null
        cachedDown = false
      } else {
        // Record the first unreachable time; leave it alone until a successful read.
        if (firstUnreachableAt === null) {
          firstUnreachableAt = at
        }
      }
    },
    status() {
      const at = now()
      if (lastReachable !== null && at - lastReachable < cacheMs) {
        cachedDown = false
      } else if (firstUnreachableAt !== null && at - firstUnreachableAt >= cacheMs) {
        cachedDown = true
      }
      return { down: cachedDown }
    }
  }
}
