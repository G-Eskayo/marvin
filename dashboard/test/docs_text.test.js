import { describe, it, expect } from 'vitest'
import { slugifyHeading, headingIndexForAnchor } from '../src/lib/docs_text.js'
import { extractOutline } from '../src/lib/docs_text.js'

describe('slugifyHeading', () => {
  it('converts lowercase heading to slug', () => {
    expect(slugifyHeading('my section')).toBe('my-section')
  })

  it('lowercases uppercase headings', () => {
    expect(slugifyHeading('My Section')).toBe('my-section')
  })

  it('replaces multiple spaces with one dash', () => {
    expect(slugifyHeading('my  big  section')).toBe('my-big-section')
  })

  it('removes special characters except dashes', () => {
    expect(slugifyHeading('My Section (beta) [wip]')).toBe('my-section-beta-wip')
  })

  it('handles accents and unicode', () => {
    expect(slugifyHeading('café résumé')).toBe('cafe-resume')
  })

  it('strips leading and trailing dashes', () => {
    expect(slugifyHeading('---leading and trailing---')).toBe('leading-and-trailing')
  })
})

describe('headingIndexForAnchor', () => {
  const outline = [
    { index: 0, level: 1, text: 'Introduction' },
    { index: 1, level: 2, text: 'Getting Started' },
    { index: 2, level: 2, text: 'Installation' },
    { index: 3, level: 1, text: 'Usage' },
    { index: 4, level: 2, text: 'Basic Example' }
  ]

  it('finds a heading by exact slug match', () => {
    expect(headingIndexForAnchor('getting-started', outline)).toBe(1)
  })

  it('finds the first heading if anchor is missing', () => {
    expect(headingIndexForAnchor('nonexistent', outline)).toBeNull()
  })

  it('is case-insensitive', () => {
    expect(headingIndexForAnchor('INSTALLATION', outline)).toBe(2)
  })

  it('handles empty anchor', () => {
    expect(headingIndexForAnchor('', outline)).toBeNull()
  })

  it('handles null anchor', () => {
    expect(headingIndexForAnchor(null, outline)).toBeNull()
  })

  it('works with empty outline', () => {
    expect(headingIndexForAnchor('anything', [])).toBeNull()
  })
})
