import { describe, it, expect } from 'vitest'
import { resolveImage } from '../src/components/Markdown.jsx'

describe('resolveImage: a repo-relative image in a doc points at the repo on GitHub', () => {
  it('takes a full owner/repo as given (the Docs tab passes G-Eskayo/marvin; the owner was doubled, 2026-10-09)', () => {
    expect(resolveImage('docs/diagrams/x.svg', 'G-Eskayo/marvin')).toBe('https://raw.githubusercontent.com/G-Eskayo/marvin/HEAD/docs/diagrams/x.svg')
  })
  it('a bare repo name is G-Eskayo\'s', () => {
    expect(resolveImage('./docs/x.png', 'marvin')).toBe('https://raw.githubusercontent.com/G-Eskayo/marvin/HEAD/docs/x.png')
  })
  it('leaves absolute and data URLs alone', () => {
    expect(resolveImage('https://x.y/z.png', 'G-Eskayo/marvin')).toBe('https://x.y/z.png')
    expect(resolveImage('data:image/png;base64,AA', 'marvin')).toBe('data:image/png;base64,AA')
  })
})
