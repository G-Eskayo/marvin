import { describe, it, expect, vi } from 'vitest'
import { createOpenPrKey } from '../src/lib/review_link.js'

// Bug 1: when WaitingOnYou calls onOpenMr with null (all-projects view),
// openPrKey should navigate to workshop with no filter, not break.
describe('App.jsx openPrKey navigation', () => {
  it('with null navigates to workshop with no filter', () => {
    const navigate = vi.fn()
    const openPrKey = createOpenPrKey(navigate)
    openPrKey(null)
    expect(navigate).toHaveBeenCalledWith('workshop')
    expect(navigate).toHaveBeenCalledOnce()
  })

  it('with bare repo navigates to workshop with projectFilter', () => {
    const navigate = vi.fn()
    const openPrKey = createOpenPrKey(navigate)
    openPrKey('acme/app')
    expect(navigate).toHaveBeenCalledWith('workshop', { projectFilter: 'acme/app' })
    expect(navigate).toHaveBeenCalledOnce()
  })

  it('with repo#number navigates to workshop with item', () => {
    const navigate = vi.fn()
    const openPrKey = createOpenPrKey(navigate)
    openPrKey('acme/app#123')
    expect(navigate).toHaveBeenCalledWith('workshop', { item: { repo: 'acme/app', pr: 123 } })
    expect(navigate).toHaveBeenCalledOnce()
  })

  it('with undefined behaves like null', () => {
    const navigate = vi.fn()
    const openPrKey = createOpenPrKey(navigate)
    openPrKey(undefined)
    expect(navigate).toHaveBeenCalledWith('workshop')
    expect(navigate).toHaveBeenCalledOnce()
  })
})
