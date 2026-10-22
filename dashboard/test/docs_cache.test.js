import { describe, it, expect } from 'vitest'
import { docsCacheFrom } from '../src/lib/docs_cache.js'

// The Docs tab's Refresh button blanked the whole window (2026-10-07): docs:refresh returns
// { generated_at, repos: [...] } like docs:repos, but the tab stored that object as `repos`,
// and RepoList's repos.map threw.
describe('docsCacheFrom', () => {
  const repos = [{ id: '__master__', name: 'Where things are' }, { id: 'marvin', name: 'marvin' }]

  it('keeps the catalog shape that docs:refresh and docs:repos return', () => {
    expect(docsCacheFrom({ generated_at: '2026-10-07T01:50:43Z', repos })).toEqual({ generated_at: '2026-10-07T01:50:43Z', repos })
  })

  it('always gives the tab an array of repos, whatever comes back', () => {
    for (const bad of [null, undefined, {}, { repos: null }, 'oops']) {
      expect(Array.isArray(docsCacheFrom(bad).repos)).toBe(true)
    }
  })

  it('accepts a bare array of repos too', () => {
    expect(docsCacheFrom(repos).repos).toEqual(repos)
  })
})

// #565: a GitHub-only project's saved copy is never mistaken for live. The words follow mock-ups
// ticket-403-f-5a (checking) and f-5b (up to date).
describe('savedCopyLine', async () => {
  const { savedCopyLine } = await import('../src/lib/docs_cache.js')
  const now = Date.parse('2026-10-21T12:00:00Z')
  const twoHours = { savedAt: now - 2 * 3600_000, checkedAt: now - 2 * 3600_000 }
  it('checking: the copy age and "checking…", with the pulsing dot', () => {
    expect(savedCopyLine(twoHours, 'checking', now)).toEqual({ text: 'from GitHub, 2 h ago · checking…', dot: 'checking' })
  })
  it('a 304 or a change applied: up to date, no age', () => {
    expect(savedCopyLine(twoHours, 'unchanged', now)).toEqual({ text: 'from GitHub · up to date', dot: 'ok' })
    expect(savedCopyLine(twoHours, 'changed', now)).toEqual({ text: 'from GitHub · up to date', dot: 'ok' })
  })
  it('offline or the gate cooling down: the age stays, and it says it could not check', () => {
    expect(savedCopyLine(twoHours, 'offline', now)).toEqual({ text: 'from GitHub, 2 h ago · could not check', dot: 'stale' })
    expect(savedCopyLine(twoHours, 'skipped', now).dot).toBe('stale')
  })
  it('the age is the last time the copy was confirmed, else when it was saved', () => {
    expect(savedCopyLine({ savedAt: now - 3 * 86400_000, checkedAt: now - 60_000 }, 'offline', now).text).toBe('from GitHub, 1 min ago · could not check')
    expect(savedCopyLine({ savedAt: now - 3 * 86400_000, checkedAt: null }, 'offline', now).text).toBe('from GitHub, 3 days ago · could not check')
  })
  it('one day reads "1 day ago", not "1 days ago"', () => {
    expect(savedCopyLine({ checkedAt: now - 30 * 3600_000 }, 'checking', now).text).toBe('from GitHub, 1 day ago · checking…')
  })
  it('no copy yet, or nonsense in: never throws, never claims an age', () => {
    expect(savedCopyLine({ savedAt: null, checkedAt: null }, 'checking', now).text).toBe('from GitHub · checking…')
    expect(savedCopyLine(null, 'offline', now).text).toBe('from GitHub · could not check')
    expect(savedCopyLine({ savedAt: 'garbage' }, 'bogus', now)).toBeNull()
  })
  it('local, master and card projects get no line', () => {
    expect(savedCopyLine(null, 'not-github', now)).toBeNull()
  })
})
