import { describe, it, expect } from 'vitest'
import { toSpeakable } from '../mobile-backend/speakable.js'

describe('speakable', () => {
  describe('toSpeakable()', () => {
    it('strips markdown links, keeping the text', () => {
      const input = 'Check out [this link](https://example.com) for more'
      const result = toSpeakable(input)
      expect(result).toContain('this link')
      expect(result).not.toContain('https://example.com')
    })

    it('strips markdown images', () => {
      const input = 'Here is ![alt text](image.png) inline'
      const result = toSpeakable(input)
      expect(result).not.toContain('image.png')
    })

    it('removes markdown formatting', () => {
      const input = 'This is **bold**, *italic*, and `code`'
      const result = toSpeakable(input)
      expect(result).toEqual('This is bold, italic, and code')
    })

    it('removes standalone URLs', () => {
      const input = 'Visit https://example.com for more info'
      const result = toSpeakable(input)
      expect(result).not.toContain('https://')
    })

    it('enforces short-reply length cap (500 chars)', () => {
      const longText = 'a'.repeat(600)
      const result = toSpeakable(longText)
      expect(result.length).toBeLessThanOrEqual(500)
    })

    it('truncates with ellipsis when exceeding cap', () => {
      const longText = 'word '.repeat(150)
      const result = toSpeakable(longText)
      expect(result).toMatch(/\.\.\.$/)
    })

    it('handles empty input', () => {
      expect(toSpeakable('')).toBe('')
    })

    it('handles input with only whitespace', () => {
      const result = toSpeakable('   \n\n  ')
      expect(result.trim()).toBe('')
    })

    it('preserves normal text without markdown', () => {
      const input = 'This is plain text without any formatting'
      expect(toSpeakable(input)).toBe(input)
    })

    it('removes backtick-style code blocks', () => {
      const input = 'Use `function()` to call it'
      const result = toSpeakable(input)
      expect(result).toBe('Use function() to call it')
    })

    it('removes underscores (markdown emphasis)', () => {
      const input = 'This is _emphasized_ text'
      const result = toSpeakable(input)
      expect(result).toBe('This is emphasized text')
    })

    it('handles mixed markdown and plain text', () => {
      const input = 'Read **[the docs](https://docs.com)** for **bold** info'
      const result = toSpeakable(input)
      expect(result).toContain('the docs')
      expect(result).toContain('bold')
      expect(result).not.toContain('https://')
      expect(result).not.toContain('**')
      expect(result).not.toContain('[]')
    })

    it('respects cap even with multiple newlines', () => {
      const input = 'line1\nline2\nline3'.repeat(100)
      const result = toSpeakable(input)
      expect(result.length).toBeLessThanOrEqual(500)
    })

    it('strips heading markdown', () => {
      const input = '# Heading\nText'
      const result = toSpeakable(input)
      expect(result).not.toContain('#')
    })
  })
})
