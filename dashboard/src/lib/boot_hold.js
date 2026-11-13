// Pure hold/release logic extracted from boot_animation.js for testability.
// This implements a hover-hold mechanism with a maximum bound, RAF watchdog, and grace period.

const GRACE_MS = 2000

export function createBootHoldController({ holdBoundMs = 8000, now = Date.now } = {}) {
  let held = false
  let grace = null
  let finished = false
  let rafCount = 0
  let lastHoldTime = null
  const maxRafCount = 100000  // watchdog: prevent infinite RAF loops

  return {
    // Check if hold should be released due to timeout
    checkHoldTimeout() {
      if (!held || finished) return false
      if (lastHoldTime !== null && now() - lastHoldTime >= holdBoundMs) {
        return true  // time to release
      }
      return false
    },

    // Release the hold, optionally triggering the animation
    release() {
      if (!held) return false
      held = false
      if (grace !== null) {
        clearTimeout(grace)
        grace = null
      }
      return true
    },

    // Enter held state
    hold(onState) {
      if (finished) return
      if (!held) {
        lastHoldTime = now()
        held = true
        if (grace !== null) {
          clearTimeout(grace)
          grace = null
        }
        onState?.({ held: true })
      }
    },

    // Exit held state with a grace period
    unhold(checkStillHovered, onState) {
      if (!held) return
      if (grace === null && !finished) {
        grace = setTimeout(() => {
          grace = null
          if (!checkStillHovered?.()) {
            this.release()
            onState?.({ held: false })
          }
        }, GRACE_MS)
      }
    },

    // Record RAF tick for watchdog
    tickRaf() {
      rafCount++
      return rafCount < maxRafCount
    },

    // Signal that animations are finished
    finish() {
      finished = true
      held = false
      if (grace !== null) {
        clearTimeout(grace)
        grace = null
      }
    },

    // Check watchdog status
    isRunning() {
      return !finished
    }
  }
}
