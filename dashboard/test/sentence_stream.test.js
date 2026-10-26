import { describe, it, expect, beforeEach } from 'vitest'
import { createSentenceStream } from '../mobile-backend/sentence_stream.js'

describe('sentence_stream', () => {
  let stream

  beforeEach(() => {
    stream = createSentenceStream()
  })

  it('returns empty array for incomplete sentences', () => {
    const result = stream.push('Hello')
    expect(result).toEqual([])
  })

  it('returns one sentence when period is encountered', () => {
    const result = stream.push('Hello. ')
    expect(result).toEqual(['Hello.'])
  })

  it('returns multiple sentences', () => {
    let result = stream.push('First. ')
    expect(result).toEqual(['First.'])

    result = stream.push('Second. ')
    expect(result).toEqual(['Second.'])
  })

  it('handles question marks as sentence boundaries', () => {
    const result = stream.push('What? ')
    expect(result).toEqual(['What?'])
  })

  it('handles exclamation marks as sentence boundaries', () => {
    const result = stream.push('Wow! ')
    expect(result).toEqual(['Wow!'])
  })

  it('returns trailing fragment on flush', () => {
    stream.push('Incomplete')
    const flushed = stream.flush()
    expect(flushed).toBe('Incomplete')
  })

  it('returns null on flush when empty', () => {
    const flushed = stream.flush()
    expect(flushed).toBeNull()
  })

  it('clears state after flush', () => {
    stream.push('Hello. ')
    stream.push('Incomplete')
    stream.flush()

    const result = stream.push('Next. ')
    expect(result).toEqual(['Next.'])
  })

  it('handles partial sentence across multiple pushes', () => {
    let result = stream.push('This is a ')
    expect(result).toEqual([])

    result = stream.push('sentence. ')
    expect(result).toEqual(['This is a sentence.'])
  })

  it('handles multiple sentences in single push', () => {
    const result = stream.push('First. Second. Third. ')
    expect(result).toEqual(['First.', 'Second.', 'Third.'])
  })

  it('trims whitespace from sentences', () => {
    const result = stream.push('   Hello.   ')
    expect(result).toEqual(['Hello.'])
  })

  it('ignores ellipsis as sentence boundary', () => {
    const result = stream.push('Wait...')
    expect(result).toEqual([])
  })

  it('handles sentence with decimal numbers', () => {
    const result = stream.push('It costs $9.99 for the item. ')
    expect(result).toEqual(['It costs $9.99 for the item.'])
  })

  it('accumulates across multiple incomplete pushes', () => {
    stream.push('First ')
    stream.push('sentence ')
    const result = stream.push('here. ')
    expect(result).toEqual(['First sentence here.'])
  })
})
