import { describe, it, expect } from 'vitest'
import { resolveImage } from '../components/Markdown.jsx'

describe('resolveImage', () => {
  it('points a repo-relative image at the repo on GitHub', () => {
    expect(resolveImage('docs/images/a.png', 'clarity-captions')).toBe('https://raw.githubusercontent.com/G-Eskayo/clarity-captions/HEAD/docs/images/a.png')
    expect(resolveImage('./a.png', 'r')).toContain('/HEAD/a.png')
  })
  it('leaves absolute and data URLs alone, and does nothing without a repo', () => {
    expect(resolveImage('https://x/y.png', 'r')).toBe('https://x/y.png')
    expect(resolveImage('data:image/png;base64,AA', 'r')).toBe('data:image/png;base64,AA')
    expect(resolveImage('a.png', undefined)).toBe('a.png')
  })
})
