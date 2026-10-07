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
