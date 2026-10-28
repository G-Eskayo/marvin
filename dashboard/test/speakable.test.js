import { describe, it, expect } from 'vitest'
import { toSpeakable, createSentenceStreamer } from '../mobile-backend/speakable.js'

describe('speakable', () => {
  describe('toSpeakable', () => {
    it('test 1: removes markdown links', () => {
      const input = 'Check [this link](https://example.com) for details'
      const output = toSpeakable(input)
      expect(output).toBe('Check this link for details')
    })

    it('removes inline code', () => {
      const input = 'Run `npm install` to set up'
      const output = toSpeakable(input)
      expect(output).toBe('Run npm install to set up')
    })

    it('removes bold text markers', () => {
      const input = 'This is **very important** text'
      const output = toSpeakable(input)
      expect(output).toBe('This is very important text')
    })

    it('removes italic text markers', () => {
      const input = 'This is *important* text'
      const output = toSpeakable(input)
      expect(output).toBe('This is important text')
    })

    it('removes header markers', () => {
      const input = '# Title\nSome content'
      const output = toSpeakable(input)
      expect(output).toBe('Title Some content')
    })

    it('removes code fences', () => {
      const input = 'Here is code:\n```javascript\nconst x = 1;\n```\nDone'
      const output = toSpeakable(input)
      expect(output).toBe('Here is code: Done')
    })

    it('cleans up extra whitespace', () => {
      const input = 'Extra   spaces   here'
      const output = toSpeakable(input)
      expect(output).toBe('Extra spaces here')
    })

    it('handles empty input', () => {
      expect(toSpeakable('')).toBe('')
      expect(toSpeakable(null)).toBe('')
    })
  })

  describe('createSentenceStreamer', () => {
    it('test 14: streams complete sentences', () => {
      const streamer = createSentenceStreamer()

      const s1 = streamer.push('This is the first ')
      expect(s1).toEqual([])

      const s2 = streamer.push('sentence. ')
      expect(s2).toEqual(['This is the first sentence.'])

      const s3 = streamer.push('And this is another.')
      expect(s3).toEqual(['And this is another.'])
    })

    it('handles question marks', () => {
      const streamer = createSentenceStreamer()

      const s1 = streamer.push('What is this? ')
      expect(s1).toEqual(['What is this?'])
    })

    it('handles exclamation marks', () => {
      const streamer = createSentenceStreamer()

      const s1 = streamer.push('This is great! ')
      expect(s1).toEqual(['This is great!'])
    })

    it('finish() emits remaining text', () => {
      const streamer = createSentenceStreamer()

      streamer.push('Incomplete sentence')
      const final = streamer.finish()
      expect(final).toEqual(['Incomplete sentence'])
    })

    it('handles multiple sentences in one push', () => {
      const streamer = createSentenceStreamer()

      const sentences = streamer.push('First. Second. Third.')
      expect(sentences).toContain('First.')
      expect(sentences).toContain('Second.')
      expect(sentences).toContain('Third.')
    })
  })
})
