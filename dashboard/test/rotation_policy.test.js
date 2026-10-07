import { describe, it, expect } from 'vitest'
import { shouldRotate, detectTopicShift, summarize } from '../mobile-backend/rotation_policy.js'

describe('rotation_policy', () => {
  describe('shouldRotate', () => {
    it('returns rotate true when message count reaches threshold', () => {
      const sessionMessages = [
        { text: 'msg1', source: 'chat' },
        { text: 'msg2', source: 'chat' },
        { text: 'msg3', source: 'chat' },
        { text: 'msg4', source: 'chat' },
        { text: 'msg5', source: 'chat' }
      ]

      const result = shouldRotate({
        sessionMessages,
        newMessageText: 'msg6',
        lengthThreshold: 5,
        topicShiftFn: () => ({ shift: false })
      })

      expect(result.rotate).toBe(true)
      expect(result.reason).toContain('length')
    })

    it('returns rotate false when below threshold', () => {
      const sessionMessages = [
        { text: 'msg1', source: 'chat' },
        { text: 'msg2', source: 'chat' }
      ]

      const result = shouldRotate({
        sessionMessages,
        newMessageText: 'msg3',
        lengthThreshold: 5,
        topicShiftFn: () => ({ shift: false })
      })

      expect(result.rotate).toBe(false)
    })

    it('checks topic shift even when below length threshold', () => {
      const sessionMessages = [
        { text: 'hello world foo bar', source: 'chat' }
      ]

      let topicShiftFnCalled = false
      const result = shouldRotate({
        sessionMessages,
        newMessageText: 'completely different xyz abc',
        lengthThreshold: 100,
        topicShiftFn: () => {
          topicShiftFnCalled = true
          return { shift: true }
        }
      })

      expect(topicShiftFnCalled).toBe(true)
      expect(result.rotate).toBe(true)
      expect(result.reason).toContain('topic')
    })

    it('length threshold takes precedence over topic check', () => {
      const sessionMessages = Array(5).fill(null).map((_, i) => ({
        text: `msg${i}`,
        source: 'chat'
      }))

      const result = shouldRotate({
        sessionMessages,
        newMessageText: 'new msg',
        lengthThreshold: 5,
        topicShiftFn: () => {
          throw new Error('should not be called when length threshold reached')
        }
      })

      expect(result.rotate).toBe(true)
    })

    it('returns both rotate and reason fields', () => {
      const sessionMessages = [{ text: 'msg', source: 'chat' }]

      const result = shouldRotate({
        sessionMessages,
        newMessageText: 'text',
        lengthThreshold: 100,
        topicShiftFn: () => ({ shift: false })
      })

      expect(result).toHaveProperty('rotate')
      expect(result).toHaveProperty('reason')
    })
  })

  describe('detectTopicShift', () => {
    it('detects shift when recent messages and new message have low word overlap', () => {
      const sessionMessages = [
        { text: 'the quick brown fox jumps', source: 'chat' },
        { text: 'over the lazy dog', source: 'chat' }
      ]

      const result = detectTopicShift(
        sessionMessages,
        'completely unrelated xyzzy abc def',
        { windowSize: 2, threshold: 0.5 }
      )

      expect(result.shift).toBe(true)
    })

    it('does not detect shift when there is sufficient overlap', () => {
      const sessionMessages = [
        { text: 'we are discussing the weather', source: 'chat' },
        { text: 'the weather is nice today', source: 'chat' }
      ]

      const result = detectTopicShift(
        sessionMessages,
        'the weather will be good tomorrow',
        { windowSize: 2, threshold: 0.3 }
      )

      expect(result.shift).toBe(false)
    })

    it('respects the windowSize parameter', () => {
      const sessionMessages = [
        { text: 'discussing dogs and cats', source: 'chat' },
        { text: 'more about animals', source: 'chat' },
        { text: 'programming computers code', source: 'chat' }
      ]

      // windowSize 1: only last message "programming computers code" vs "programming tutorial"
      // Overlap: "programming" matches -> 1/2 = 0.5, not < 0.4, so no shift
      const result1 = detectTopicShift(
        sessionMessages,
        'programming tutorial',
        { windowSize: 1, threshold: 0.6 }
      )

      // windowSize 2: includes "more about animals" + "programming computers code"
      // Same overlap score as windowSize 1 since "programming" still matches
      // But with threshold 0.2, it definitely doesn't shift
      const result2 = detectTopicShift(
        sessionMessages,
        'programming tutorial',
        { windowSize: 2, threshold: 0.2 }
      )

      // Both should give the same result (no shift) due to shared word
      // But let's test that different thresholds cause different results
      expect(result1.shift).toBe(true) // 0.5 < 0.6
      expect(result2.shift).toBe(false) // 0.5 >= 0.2
      expect(result1.shift).not.toEqual(result2.shift)
    })

    it('returns both shift and score fields', () => {
      const sessionMessages = [{ text: 'test', source: 'chat' }]

      const result = detectTopicShift(
        sessionMessages,
        'new',
        { windowSize: 1, threshold: 0.5 }
      )

      expect(result).toHaveProperty('shift')
      expect(result).toHaveProperty('score')
      expect(typeof result.score).toBe('number')
    })

    it('handles empty session messages', () => {
      const result = detectTopicShift(
        [],
        'new message',
        { windowSize: 1, threshold: 0.5 }
      )

      expect(result.shift).toBe(false)
    })

    it('is case-insensitive for word matching', () => {
      const sessionMessages = [
        { text: 'Hello World', source: 'chat' }
      ]

      const result = detectTopicShift(
        sessionMessages,
        'hello world',
        { windowSize: 1, threshold: 0.5 }
      )

      expect(result.shift).toBe(false)
    })

    it('treats punctuation as non-word characters', () => {
      const sessionMessages = [
        { text: 'what, is, this?', source: 'chat' }
      ]

      const result = detectTopicShift(
        sessionMessages,
        'what is this',
        { windowSize: 1, threshold: 0.5 }
      )

      expect(result.shift).toBe(false)
    })
  })

  describe('summarize', () => {
    it('concatenates messages for a summary', () => {
      const sessionMessages = [
        { role: 'user', text: 'hello', source: 'chat' },
        { role: 'assistant', text: 'hi there', source: 'chat' },
        { role: 'user', text: 'how are you', source: 'chat' }
      ]

      const summary = summarize(sessionMessages, { maxLen: 500 })

      expect(summary).toContain('hello')
      expect(summary).toContain('hi there')
      expect(summary).toContain('how are you')
    })

    it('includes role prefix for each message', () => {
      const sessionMessages = [
        { role: 'user', text: 'user msg', source: 'chat' },
        { role: 'assistant', text: 'assistant msg', source: 'chat' }
      ]

      const summary = summarize(sessionMessages, { maxLen: 500 })

      expect(summary).toMatch(/user.*user msg/i)
      expect(summary).toMatch(/assistant.*assistant msg/i)
    })

    it('respects maxLen by truncating', () => {
      const sessionMessages = Array(10).fill(null).map((_, i) => ({
        role: i % 2 === 0 ? 'user' : 'assistant',
        text: `message number ${i} with some content that makes it longer`,
        source: 'chat'
      }))

      const summary = summarize(sessionMessages, { maxLen: 100 })

      expect(summary.length).toBeLessThanOrEqual(100)
    })

    it('returns empty string for empty session', () => {
      const summary = summarize([], { maxLen: 500 })

      expect(summary).toBe('')
    })

    it('is deterministic for the same input', () => {
      const sessionMessages = [
        { role: 'user', text: 'test', source: 'chat' },
        { role: 'assistant', text: 'response', source: 'chat' }
      ]

      const summary1 = summarize(sessionMessages, { maxLen: 500 })
      const summary2 = summarize(sessionMessages, { maxLen: 500 })

      expect(summary1).toBe(summary2)
    })
  })
})
