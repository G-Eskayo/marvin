import { describe, it, expect } from 'vitest'
import { reviewTarget } from '../src/lib/review_link.js'

describe('reviewTarget (bug 1 fix)', () => {
  it('repo#number opens the PR item', () => {
    const target = reviewTarget('acme/app#123')
    expect(target).toEqual({ item: { repo: 'acme/app', pr: 123 } })
  })
  it('bare repo navigates to workshop with project filter', () => {
    const target = reviewTarget('acme/app')
    expect(target).toEqual({ projectFilter: 'acme/app' })
  })
  it('null returns null so openPrKey can fall back to unfiltered navigation', () => {
    const target = reviewTarget(null)
    expect(target).toBeNull()
  })
  it('undefined returns null', () => {
    const target = reviewTarget(undefined)
    expect(target).toBeNull()
  })
})
