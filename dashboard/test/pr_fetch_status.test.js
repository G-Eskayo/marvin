import { describe, it, expect } from 'vitest'
import { prFetchBanner } from '../src/lib/pr_fetch_status.js'

describe('prFetchBanner: merge server down', () => {
  it('test 17: when mergeServerUp is false, show amber banner about the Mac mini', () => {
    const banner = prFetchBanner({ errors: [], mergeServerUp: false })
    expect(banner?.tone).toBe('amber')
    expect(banner?.text).toMatch(/Mac mini/)
    expect(banner?.text).toMatch(/answering/)
  })

  it('test 18: when mergeServerUp is true or not provided, no merge-server-specific banner', () => {
    const banner1 = prFetchBanner({ errors: [], mergeServerUp: true })
    const banner2 = prFetchBanner({ errors: [] })
    expect(banner1).toBe(null)
    expect(banner2).toBe(null)
  })
})
