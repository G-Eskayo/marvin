import { describe, it, expect } from 'vitest'
import { resolveImage, safeMarkdownUrl } from '../src/components/Markdown.jsx'

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

describe('safeMarkdownUrl: filter URLs for markdown rendering', () => {
  it('passes through file:// URLs unchanged (dashboard local files)', () => {
    expect(safeMarkdownUrl('file:///Users/gileskayo/Documents/file.txt')).toBe('file:///Users/gileskayo/Documents/file.txt')
  })

  it('passes through safe web URLs', () => {
    expect(safeMarkdownUrl('https://example.com')).toBe('https://example.com')
    expect(safeMarkdownUrl('http://example.com')).toBe('http://example.com')
  })

  it('passes through mailto: links', () => {
    expect(safeMarkdownUrl('mailto:user@example.com')).toBe('mailto:user@example.com')
  })

  it('passes through dash:// links (dashboard internal links)', () => {
    expect(safeMarkdownUrl('dash://ticket/G-Eskayo/marvin/123')).toBe('dash://ticket/G-Eskayo/marvin/123')
    expect(safeMarkdownUrl('dash://doc/marvin/docs/ADR.md')).toBe('dash://doc/marvin/docs/ADR.md')
  })

  it('passes through repo-relative URLs', () => {
    expect(safeMarkdownUrl('docs/file.md')).toBe('docs/file.md')
    expect(safeMarkdownUrl('./path/to/file')).toBe('./path/to/file')
  })

  it('blocks javascript: and other unsafe schemes', () => {
    expect(safeMarkdownUrl('javascript:alert(1)')).toBe('')
    expect(safeMarkdownUrl('vbscript:msgbox(1)')).toBe('')
    expect(safeMarkdownUrl('x-apple-script://run')).toBe('')
  })

  it('blocks protocol-relative URLs', () => {
    expect(safeMarkdownUrl('//example.com')).toBe('')
  })

  it('blocks empty URLs', () => {
    expect(safeMarkdownUrl('')).toBe('')
    expect(safeMarkdownUrl(null)).toBe('')
  })
})
