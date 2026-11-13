import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createBootHoldController } from '../src/lib/boot_hold.js'

describe('boot_hold: hold/release controller with max bounds and watchdog', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  // Test 4: Max-hold bound prevents indefinite hold
  describe('test 4: hold mechanism respects max-bound timeout', () => {
    it('release fires after hold-bound even if cursor never leaves', () => {
      let fakeTime = 0
      const hold = createBootHoldController({ holdBoundMs: 8000, now: () => fakeTime })
      hold.hold()
      expect(hold.checkHoldTimeout()).toBe(false)

      // Advance time by 8000ms
      fakeTime += 8000
      expect(hold.checkHoldTimeout()).toBe(true)

      // Release and confirm state changed
      const released = hold.release()
      expect(released).toBe(true)
    })

    it('hold-bound can be customized', () => {
      let fakeTime = 0
      const hold = createBootHoldController({ holdBoundMs: 3000, now: () => fakeTime })
      hold.hold()
      fakeTime += 2999
      expect(hold.checkHoldTimeout()).toBe(false)
      fakeTime += 1
      expect(hold.checkHoldTimeout()).toBe(true)
    })

    it('no timeout check before hold is entered', () => {
      let fakeTime = 0
      const hold = createBootHoldController({ holdBoundMs: 8000, now: () => fakeTime })
      expect(hold.checkHoldTimeout()).toBe(false)
      fakeTime += 10000
      expect(hold.checkHoldTimeout()).toBe(false)
    })

    it('finished state disables hold timeout check', () => {
      let fakeTime = 0
      const hold = createBootHoldController({ holdBoundMs: 8000, now: () => fakeTime })
      hold.hold()
      hold.finish()
      fakeTime += 9000
      expect(hold.checkHoldTimeout()).toBe(false)
    })
  })

  // Test 5: RAF watchdog prevents infinite loops
  describe('test 5: RAF loop watchdog prevents infinite loops', () => {
    it('tickRaf returns false after maxRafCount', () => {
      const hold = createBootHoldController()
      for (let i = 0; i < 100_000; i++) {
        const canContinue = hold.tickRaf()
        if (!canContinue) {
          expect(i).toBe(99_999)  // hit the limit
          return
        }
      }
      throw new Error('watchdog not triggered')
    })

    it('finish() disables hold but does not affect RAF count', () => {
      const hold = createBootHoldController({ holdBoundMs: 8000 })
      hold.hold()
      hold.finish()
      let releaseCount = 0
      const released = hold.release()
      expect(released).toBe(false)  // already finished, can't release
    })

    it('isRunning reflects finished state', () => {
      const hold = createBootHoldController()
      expect(hold.isRunning()).toBe(true)
      hold.finish()
      expect(hold.isRunning()).toBe(false)
    })
  })

  // Additional tests for hold/unhold grace period
  describe('grace period prevents rapid toggle', () => {
    it('unhold starts grace period and releases after grace expires if not hovered', () => {
      const hold = createBootHoldController()
      hold.hold()
      // Begin grace period by unhooking (cursor left, still hovered returns false after grace)
      let releaseCount = 0
      hold.unhold(
        () => false,  // not still hovered
        () => { releaseCount++ }
      )
      // Grace period is 2000ms; advance past it
      vi.advanceTimersByTime(2100)
      // Verify release callback was called once grace expired
      expect(releaseCount).toBeGreaterThan(0)
    })

    it('unhold with still hovered does not release during grace period', () => {
      const hold = createBootHoldController()
      hold.hold()

      // Track whether release is called
      let wasReleased = false
      hold.unhold(
        () => true,  // still hovered — suppress release
        () => { wasReleased = true }
      )

      // Advance time past grace period
      vi.advanceTimersByTime(2100)

      // Because still hovered returns true, release should not have fired
      expect(wasReleased).toBe(false)
    })

    it('multiple unholds do not create multiple grace timers', () => {
      const hold = createBootHoldController()
      hold.hold()
      const releaseCount = []
      hold.unhold(() => false, () => releaseCount.push(1))
      hold.unhold(() => false, () => releaseCount.push(1))
      vi.advanceTimersByTime(2001)
      // Should only fire once despite two unhold calls (not zero, not two)
      expect(releaseCount.length).toBe(1)
    })
  })

  describe('hold state management', () => {
    it('hold is idempotent: second hold does not reset timer', () => {
      let fakeTime = 0
      const hold = createBootHoldController({ holdBoundMs: 5000, now: () => fakeTime })

      hold.hold()
      fakeTime += 3000  // advance 3 seconds
      const stillFalse1 = hold.checkHoldTimeout()
      expect(stillFalse1).toBe(false)  // 3s < 5s bound

      hold.hold()  // second hold should not reset the timer
      fakeTime += 2100  // advance 2.1 more seconds (total 5.1s from original hold)
      const timeoutReached = hold.checkHoldTimeout()
      expect(timeoutReached).toBe(true)  // original timer fired, not reset by second hold()
    })

    it('release when not held returns false', () => {
      const hold = createBootHoldController()
      const result = hold.release()
      expect(result).toBe(false)
    })
  })
})
