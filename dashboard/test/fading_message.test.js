import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { createFadingMessage, MESSAGE_FADE_MS } from '../src/lib/fading_message.js'

describe('fading_message', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('MESSAGE_FADE_MS', () => {
    it('exports a fade duration constant', () => {
      expect(MESSAGE_FADE_MS).toBeGreaterThan(0)
      expect(MESSAGE_FADE_MS).toBeLessThanOrEqual(10000)
    })
  })

  describe('createFadingMessage', () => {
    it('returns a setState scheduler function', () => {
      const fn = createFadingMessage()
      expect(typeof fn).toBe('function')
    })

    it('schedules message fade after MESSAGE_FADE_MS', () => {
      const fn = createFadingMessage()
      let lastState = null
      const setState = (s) => { lastState = s }
      const timeoutRef = { current: null }

      fn(setState, timeoutRef, { message: 'Test message', error: false })
      expect(lastState.message).toBe('Test message')
      expect(timeoutRef.current).not.toBeNull()

      vi.advanceTimersByTime(MESSAGE_FADE_MS)
      expect(lastState.message).toBeNull()
    })

    it('clears existing timeout before setting new one', () => {
      const fn = createFadingMessage()
      let callCount = 0
      const setState = (s) => { callCount++ }
      const timeoutRef = { current: null }

      fn(setState, timeoutRef, { message: 'First', error: false })
      const firstTimeout = timeoutRef.current
      vi.advanceTimersByTime(MESSAGE_FADE_MS / 2)

      fn(setState, timeoutRef, { message: 'Second', error: false })
      const secondTimeout = timeoutRef.current
      expect(secondTimeout).not.toBe(firstTimeout)

      vi.advanceTimersByTime(MESSAGE_FADE_MS)
      expect(callCount).toBeGreaterThan(0)
    })

    it('does not schedule fade if message is null', () => {
      const fn = createFadingMessage()
      const setState = vi.fn()
      const timeoutRef = { current: null }

      fn(setState, timeoutRef, { message: null, error: false })
      expect(timeoutRef.current).toBeNull()
    })

    it('handles multiple sequential messages', () => {
      const fn = createFadingMessage()
      let lastState = null
      const setState = (s) => { lastState = s }
      const timeoutRef = { current: null }

      fn(setState, timeoutRef, { message: 'First', error: false })
      vi.advanceTimersByTime(MESSAGE_FADE_MS + 100)
      expect(lastState.message).toBeNull()

      fn(setState, timeoutRef, { message: 'Second', error: true })
      expect(lastState.message).toBe('Second')
      expect(lastState.error).toBe(true)

      vi.advanceTimersByTime(MESSAGE_FADE_MS)
      expect(lastState.message).toBeNull()
    })
  })
})
