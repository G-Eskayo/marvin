import { describe, it, expect } from 'vitest'
import { selectContentPage } from '../src/lib/screenshot_capture.js'

describe('selectContentPage', () => {
  it('returns the first non-devtools page', () => {
    const pages = [
      { url: () => 'devtools://whatever' },
      { url: () => 'http://localhost:5173/' },
      { url: () => 'http://localhost:5173/other' },
    ]
    expect(selectContentPage(pages)).toBe(pages[1])
  })

  it('skips devtools:// pages', () => {
    const pages = [
      { url: () => 'devtools://one' },
      { url: () => 'devtools://two' },
      { url: () => 'about:blank' },
    ]
    expect(selectContentPage(pages)).toBe(pages[2])
  })

  it('returns null when there are no pages', () => {
    expect(selectContentPage([])).toBe(null)
  })

  it('returns null when all pages are devtools', () => {
    const pages = [
      { url: () => 'devtools://one' },
      { url: () => 'devtools://two' },
    ]
    expect(selectContentPage(pages)).toBe(null)
  })

  it('handles pages with missing or falsy url methods', () => {
    const pages = [
      { url: () => '' },
      { url: () => 'http://localhost:5173/' },
    ]
    expect(selectContentPage(pages)).toBe(pages[1])
  })
})
