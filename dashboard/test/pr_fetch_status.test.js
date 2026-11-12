import { describe, it, expect } from 'vitest'
import { reviewDotStatus, prFetchBanner } from '../src/lib/pr_fetch_status.js'

describe('reviewDotStatus', () => {
  const now = Date.now()

  it('returns dot as status and note as null when fetch is null', () => {
    const result = reviewDotStatus({ status: 'red', fetch: null }, now)
    expect(result).toEqual({ dot: 'red', note: null })
  })

  it('returns dot as status and note as null when no banner', () => {
    const result = reviewDotStatus({ status: 'blue', fetch: { errors: [], projects: 1 } }, now)
    expect(result).toEqual({ dot: 'blue', note: null })
  })

  it('returns dot as status and note as null when banner is info tone', () => {
    const fetch = {
      errors: [],
      projects: 1,
      source: { from: 'mini', state: 'fresh', text: 'Read from the Mini, 2 min ago.' }
    }
    const result = reviewDotStatus({ status: 'green', fetch }, now)
    expect(result).toEqual({ dot: 'green', note: null })
  })

  it('returns dot as grey with mini source text when banner is red with mini source', () => {
    const fetch = {
      errors: [{ repo: 'test/repo', message: 'connection error' }],
      projects: 1,
      lastGoodAt: now - 5 * 60_000,
      source: { from: 'mini', state: 'missing', text: "The Mini isn't answering." }
    }
    const result = reviewDotStatus({ status: 'red', fetch }, now)
    expect(result.dot).toBe('grey')
    expect(result.note).toBe("The Mini isn't answering.")
  })

  it('returns dot as grey with fallback text when banner is red without mini source', () => {
    const fetch = {
      errors: Array.from({ length: 3 }, (_, i) => ({
        repo: `G-Eskayo/r${i}`,
        message: 'HTTP 401'
      })),
      projects: 3,
      lastGoodAt: null
    }
    const result = reviewDotStatus({ status: 'blue', fetch }, now)
    expect(result.dot).toBe('grey')
    expect(result.note).toBe("Couldn't reach GitHub")
  })

  it('returns dot as status with amber banner text when banner is amber', () => {
    const fetch = {
      errors: [{ repo: 'G-Eskayo/nourished', message: 'HTTP 429' }],
      projects: 3,
      lastGoodAt: now - 10_000
    }
    const result = reviewDotStatus({ status: 'blue', fetch }, now)
    expect(result.dot).toBe('blue')
    expect(result.note).toMatch(/Couldn't read.*nourished/)
  })
})
