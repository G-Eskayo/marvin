import { describe, it, expect } from 'vitest'
import { toSpeakable } from '../mobile-backend/to_speakable.js'

describe('toSpeakable', () => {
  it('strips markdown bold/italic', () => {
    expect(toSpeakable('This is **bold** and *italic* text')).toBe('This is bold and italic text')
  })

  it('strips markdown headers', () => {
    expect(toSpeakable('# Header 1\n## Header 2\nBody')).toBe('Header 1\nHeader 2\nBody')
  })

  it('strips markdown lists', () => {
    expect(toSpeakable('- Item 1\n- Item 2\nText')).toBe('Item 1\nItem 2\nText')
  })

  it('strips code fences', () => {
    expect(toSpeakable('Here is code:\n```javascript\nconst x = 1\n```\nEnd')).toBe(
      'Here is code:\nconst x = 1\nEnd'
    )
  })

  it('converts links to text', () => {
    expect(toSpeakable('Check [this link](https://example.com) for more')).toBe(
      'Check this link for more'
    )
  })

  it('strips bare URLs', () => {
    expect(toSpeakable('Visit https://example.com or http://test.org for details')).toBe(
      'Visit or for details'
    )
  })

  it('collapses multiple whitespace', () => {
    expect(toSpeakable('Text   with   many    spaces')).toBe('Text with many spaces')
  })

  it('collapses multiple newlines', () => {
    expect(toSpeakable('Line 1\n\n\n\nLine 2')).toBe('Line 1\n\nLine 2')
  })

  it('handles combined markdown and URLs', () => {
    expect(toSpeakable('**Bold** text with [link](https://example.com) and https://bare.url')).toBe(
      'Bold text with link and'
    )
  })

  it('trims leading/trailing whitespace', () => {
    expect(toSpeakable('  text  ')).toBe('text')
  })

  it('handles empty string', () => {
    expect(toSpeakable('')).toBe('')
  })

  it('handles code inline backticks', () => {
    expect(toSpeakable('Use `const x = 1` in your code')).toBe('Use const x = 1 in your code')
  })
})
