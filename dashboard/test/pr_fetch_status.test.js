import { describe, it, expect } from 'vitest'
import { prFetchBanner } from '../src/lib/pr_fetch_status.js'

describe('prFetchBanner: merge server health', () => {
  it('returns amber banner when mergeServer.down is true', () => {
    const result = prFetchBanner({ mergeServer: { down: true } })
    expect(result).toBeTruthy()
    expect(result.tone).toBe('amber')
    expect(result.text).toMatch(/Mac mini.*isn't answering.*approvals will wait/)
  })

  it('returns null when mergeServer.down is false and no errors', () => {
    const result = prFetchBanner({ mergeServer: { down: false } })
    expect(result).toBeNull()
  })

  it('returns null when mergeServer is null and no errors', () => {
    const result = prFetchBanner({ mergeServer: null })
    expect(result).toBeNull()
  })

  it('GitHub errors take precedence over merge server down', () => {
    const result = prFetchBanner({
      errors: [{ repo: 'G-Eskayo/marvin', message: 'ECONNREFUSED' }],
      projects: 1,
      mergeServer: { down: true }
    })
    expect(result.tone).toBe('red') // GitHub error, not merge server message
    expect(result.text).toMatch(/Couldn't reach GitHub/)
  })

  it('mini feed precedence over merge server down', () => {
    const result = prFetchBanner({
      source: { from: 'mini', state: 'stale', text: 'Mini stopped answering' },
      mergeServer: { down: true }
    })
    expect(result.text).toBe('Mini stopped answering')
  })
})
