import { describe, it, expect } from 'vitest'
import { toSpeakable, capSpoken, createSentenceStream } from '../mobile-backend/speakable.js'

describe('toSpeakable', () => {
  it('strips Markdown emphasis, headings, code and list markers', () => {
    const md = '## Status\n\n**Main** is _green_.\n\n- PR `#657` merged\n- 2 tickets left\n\n```js\nconst x = 1\n```'
    const out = toSpeakable(md)
    expect(out).not.toMatch(/[*_`#]{2,}|```|^\s*-\s/m)
    expect(out).toContain('Main is green.')
    expect(out).toContain('PR #657 merged')
    expect(out).not.toContain('const x')
  })

  it('reads a Markdown link as its text and never reads the URL aloud', () => {
    const out = toSpeakable('See [the PR](https://github.com/G-Eskayo/marvin/pull/657) for details.')
    expect(out).toBe('See the PR for details.')
  })

  it('replaces a bare URL with its site name', () => {
    const out = toSpeakable('It is at https://www.example.com/some/long/path?q=1 now.')
    expect(out).not.toMatch(/https?:|\/\//)
    expect(out).toContain('example.com')
  })

  it('drops tables, HTML tags and blockquote markers', () => {
    const out = toSpeakable('> quoted\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n<b>bold</b>')
    expect(out).not.toMatch(/[|<>]/)
    expect(out).toContain('quoted')
    expect(out).toContain('bold')
  })

  it('returns an empty string for empty, null or non-string input instead of throwing', () => {
    expect(toSpeakable('')).toBe('')
    expect(toSpeakable(null)).toBe('')
    expect(toSpeakable(undefined)).toBe('')
    expect(toSpeakable(42)).toBe('')
    expect(toSpeakable('   \n\n  ')).toBe('')
  })

  it('keeps numbers with decimal points and version strings intact', () => {
    expect(toSpeakable('Version 0.83.0 is out, 1.5 s faster.')).toBe('Version 0.83.0 is out, 1.5 s faster.')
  })
})

describe('capSpoken', () => {
  it('leaves a short reply whole', () => {
    expect(capSpoken('One. Two.')).toEqual({ speech: 'One. Two.', truncated: false })
  })

  it('cuts a long reply at a sentence boundary and says the rest is on the phone', () => {
    const long = Array.from({ length: 40 }, (_, i) => `Sentence number ${i} is here.`).join(' ')
    const { speech, truncated } = capSpoken(long, { maxSentences: 3, maxChars: 400 })
    expect(truncated).toBe(true)
    expect(speech.startsWith('Sentence number 0 is here. Sentence number 1 is here. Sentence number 2 is here.')).toBe(true)
    expect(speech).toMatch(/phone/i)
    expect(speech).not.toContain('Sentence number 3')
  })

  it('caps one enormous sentence with no punctuation by characters, at a word boundary', () => {
    const huge = 'word '.repeat(2000).trim()
    const { speech, truncated } = capSpoken(huge, { maxSentences: 3, maxChars: 300 })
    expect(truncated).toBe(true)
    expect(speech.length).toBeLessThan(400)
    expect(speech).not.toMatch(/wor\b(?!d)/)
  })

  it('handles empty input', () => {
    expect(capSpoken('')).toEqual({ speech: '', truncated: false })
  })
})

describe('createSentenceStream', () => {
  it('emits each sentence as soon as it finishes, across token boundaries', () => {
    const s = createSentenceStream()
    const out = []
    for (const tok of ['Hel', 'lo there', '. How', ' are', ' you? I am', ' fine']) out.push(...s.push(tok))
    expect(out).toEqual(['Hello there.', 'How are you?'])
    expect(s.flush()).toEqual(['I am fine'])
  })

  it('does not split on decimals, versions or common abbreviations', () => {
    const s = createSentenceStream()
    const out = [...s.push('Version 0.83.0 shipped, e.g. the voice bit. Dr. Who is 1.5 s. Done.')]
    expect(out).toEqual(['Version 0.83.0 shipped, e.g. the voice bit.', 'Dr. Who is 1.5 s.'])
    expect(s.flush()).toEqual(['Done.'])
  })

  it('yields speakable sentences (Markdown removed) and skips empty ones', () => {
    const s = createSentenceStream()
    const out = [...s.push('**Bold** start. ... '), ...s.flush()]
    expect(out).toEqual(['Bold start.'])
  })

  it('flushes nothing from an empty stream', () => {
    expect(createSentenceStream().flush()).toEqual([])
  })
})
