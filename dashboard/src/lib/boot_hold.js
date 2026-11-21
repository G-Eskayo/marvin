// Hold/release decision for boot animation: extracted from boot_animation.js for testing.
// Prevents indefinite hold when no mouse is attached (mac-mini-2012's real condition).

export function createBootHoldController(animation, { maxHoldMs = 8000, graceMs = 2000, getFinished = () => false, getReleased = () => false } = {}) {
  let held = false
  let grace = null
  let maxHoldTimer = null
  let disposed = false

  const fadeStart = animation.effect.getTiming().delay

  const dispose = () => {
    disposed = true
    clearTimeout(grace)
    clearTimeout(maxHoldTimer)
    grace = null
    maxHoldTimer = null
  }

  const release = () => {
    clearTimeout(grace)
    clearTimeout(maxHoldTimer)
    grace = null
    maxHoldTimer = null
    if (!held) return
    held = false
    if ((animation.currentTime ?? 0) < fadeStart) animation.currentTime = fadeStart
    animation.play()
  }

  const hold = (on) => {
    if (getReleased()) return release()
    if (getFinished()) {
      dispose()
      return
    }
    if (on) {
      clearTimeout(grace)
      grace = null
      if (!held && (animation.currentTime ?? 0) < fadeStart) {
        held = true
        animation.pause()
        // Force-release after maxHoldMs even if no user interaction (no mouse case)
        maxHoldTimer = setTimeout(() => {
          if (disposed) return
          maxHoldTimer = null
          release()
        }, maxHoldMs)
      }
      return
    }
    if (held && !grace) {
      grace = setTimeout(() => {
        grace = null
        // Check if still hovering; if not, release
        if (!held) return
        release()
      }, graceMs)
    }
  }

  return { hold, release, dispose }
}
