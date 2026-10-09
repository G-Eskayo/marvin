import { describe, it, expect, vi } from 'vitest'
import { listOpenPrsAcrossRepos, prKey, normalizeSeen, canMergeFromDashboard, MARVIN_REPO } from '../electron/main/mr_repos.js'
import { listPipelinePrs } from '../electron/main/mr_review.js'
import { computeReviewStatus } from '../electron/main/mr_seen.js'

describe('listOpenPrsAcrossRepos', () => {
  it('tags every PR with its repo, always includes marvin, and merges the lists', async () => {
    const ghList = vi.fn(async (repo) => (repo === MARVIN_REPO ? [{ number: 5, title: 'a', url: 'u1', body: '' }] : [{ number: 5, title: 'b', url: 'u2', body: '' }]))
    const { prs } = await listOpenPrsAcrossRepos(['G-Eskayo/clarity-captions'], ghList)
    expect(prs.map((p) => [p.repo, p.number])).toEqual([[MARVIN_REPO, 5], ['G-Eskayo/clarity-captions', 5]])
  })

  it('does not list marvin twice when it is also registered', async () => {
    const ghList = vi.fn(async () => [])
    await listOpenPrsAcrossRepos([MARVIN_REPO, 'o/x'], ghList)
    expect(ghList.mock.calls.map((c) => c[0])).toEqual([MARVIN_REPO, 'o/x'])
  })

  it('isolates one failing repo: the others still list and the failure is reported', async () => {
    const ghList = async (repo) => {
      if (repo === 'o/bad') throw new Error('404')
      return [{ number: 1, title: 't', url: 'u', body: '' }]
    }
    const { prs, errors } = await listOpenPrsAcrossRepos(['o/bad', 'o/good'], ghList)
    expect(prs.map((p) => p.repo)).toEqual([MARVIN_REPO, 'o/good'])
    expect(errors).toEqual([{ repo: 'o/bad', message: '404' }])
  })
})

describe('keys, seen-tracking and merge permission', () => {
  it('qualifies PR numbers by repo so two projects can both have a #5', () => {
    expect(prKey('o/a', 5)).toBe('o/a#5')
    expect(prKey('o/a', 5)).not.toBe(prKey('o/b', 5))
  })

  it('reads legacy bare numbers in the seen file as marvin PRs', () => {
    expect(normalizeSeen([3, 'o/x#4'])).toEqual([`${MARVIN_REPO}#3`, 'o/x#4'])
    const open = [prKey(MARVIN_REPO, 3), prKey('o/x', 3)]
    expect(computeReviewStatus(open, normalizeSeen([3]))).toBe('red') // o/x#3 is a different, unseen PR
  })

  it('only marvin PRs can be approved or denied from the dashboard', () => {
    expect(canMergeFromDashboard(MARVIN_REPO)).toBe(true)
    expect(canMergeFromDashboard('G-Eskayo/clarity-captions')).toBe(false)
  })
})

describe('listPipelinePrs carries repo identity through', () => {
  it('adds repo, key and canMerge to each PR', async () => {
    const out = await listPipelinePrs(async () => [{ number: 7, title: 't', url: 'u', body: 'Closes #2', repo: 'G-Eskayo/clarity-captions' }])
    expect(out[0]).toMatchObject({ repo: 'G-Eskayo/clarity-captions', key: 'G-Eskayo/clarity-captions#7', canMerge: false })
  })
})

import { repoFromPrUrl } from '../electron/main/mr_repos.js'

describe('repoFromPrUrl', () => {
  it('extracts owner/repo from a GitHub PR url, and refuses anything else', () => {
    expect(repoFromPrUrl('https://github.com/G-Eskayo/marvin/pull/123')).toBe('G-Eskayo/marvin')
    expect(repoFromPrUrl('https://github.com/G-Eskayo/clarity-captions/pull/4')).toBe('G-Eskayo/clarity-captions')
    expect(repoFromPrUrl('https://evil.example/G-Eskayo/marvin/pull/1')).toBeNull()
    expect(repoFromPrUrl('not a url')).toBeNull()
    expect(repoFromPrUrl(undefined)).toBeNull()
  })
})

describe('canMergeFromDashboard with opted-in projects', () => {
  it('allows marvin always, and another project only when its profile opted in', () => {
    const opted = new Set(['G-Eskayo/clarity-captions'])
    expect(canMergeFromDashboard(MARVIN_REPO, opted)).toBe(true)
    expect(canMergeFromDashboard('G-Eskayo/clarity-captions', opted)).toBe(true)
    expect(canMergeFromDashboard('G-Eskayo/killer-sudoku', opted)).toBe(false)
    expect(canMergeFromDashboard('G-Eskayo/clarity-captions')).toBe(false)
  })

  it('listPipelinePrs marks each PR with the permission it was given', async () => {
    const opted = new Set(['G-Eskayo/clarity-captions'])
    const out = await listPipelinePrs(
      async () => [
        { number: 1, title: 'a', url: 'u', body: '', repo: 'G-Eskayo/clarity-captions' },
        { number: 2, title: 'b', url: 'u', body: '', repo: 'G-Eskayo/killer-sudoku' }
      ],
      { canMerge: (repo) => canMergeFromDashboard(repo, opted) }
    )
    expect(out.map((p) => p.canMerge)).toEqual([true, false])
  })
})

import { createListCache } from '../electron/main/mr_repos.js'

describe('createListCache: per-repo cache with scoped invalidation', () => {
  it('caches each repo\'s PRs independently', async () => {
    const calls = { marvin: 0, clarity: 0 }
    const cache = createListCache({
      full: async (repo) => {
        if (repo === MARVIN_REPO) calls.marvin++
        if (repo === 'G-Eskayo/clarity-captions') calls.clarity++
        return [{ number: 1, title: 'test', repo }]
      },
      light: async (repo) => []
    }, 5 * 60_000)

    // First fetch for marvin and clarity
    await cache.getRepo(MARVIN_REPO)
    await cache.getRepo('G-Eskayo/clarity-captions')
    expect(calls).toEqual({ marvin: 1, clarity: 1 })

    // Second fetch uses cache (no new calls)
    await cache.getRepo(MARVIN_REPO)
    await cache.getRepo('G-Eskayo/clarity-captions')
    expect(calls).toEqual({ marvin: 1, clarity: 1 })
  })

  it('invalidating one repo does not invalidate others', async () => {
    const calls = { marvin: 0, clarity: 0 }
    const cache = createListCache({
      full: async (repo) => {
        if (repo === MARVIN_REPO) calls.marvin++
        if (repo === 'G-Eskayo/clarity-captions') calls.clarity++
        return []
      },
      light: async (repo) => []
    }, 5 * 60_000)

    // Cache both repos
    await cache.getRepo(MARVIN_REPO)
    await cache.getRepo('G-Eskayo/clarity-captions')
    expect(calls).toEqual({ marvin: 1, clarity: 1 })

    // Invalidate marvin only
    cache.invalidate(MARVIN_REPO)

    // Marvin needs a fresh fetch, clarity still cached
    await cache.getRepo(MARVIN_REPO)
    await cache.getRepo('G-Eskayo/clarity-captions')
    expect(calls).toEqual({ marvin: 2, clarity: 1 })
  })

  it('invalidating with no repo clears everything (legacy behavior)', async () => {
    const calls = { marvin: 0, clarity: 0 }
    const cache = createListCache({
      full: async (repo) => {
        if (repo === MARVIN_REPO) calls.marvin++
        if (repo === 'G-Eskayo/clarity-captions') calls.clarity++
        return []
      },
      light: async (repo) => []
    }, 5 * 60_000)

    // Cache both repos
    await cache.getRepo(MARVIN_REPO)
    await cache.getRepo('G-Eskayo/clarity-captions')
    expect(calls).toEqual({ marvin: 1, clarity: 1 })

    // Invalidate everything (no repo arg)
    cache.invalidate()

    // Both need fresh fetches
    await cache.getRepo(MARVIN_REPO)
    await cache.getRepo('G-Eskayo/clarity-captions')
    expect(calls).toEqual({ marvin: 2, clarity: 2 })
  })

  it('getAllRepos returns the union of all repos\' PRs', async () => {
    const cache = createListCache({
      full: async (repo) => [
        { number: repo === MARVIN_REPO ? 1 : 7, title: `${repo} PR`, repo }
      ],
      light: async (repo) => []
    }, 5 * 60_000)

    const { prs } = await cache.getAllRepos([MARVIN_REPO, 'G-Eskayo/clarity-captions'])
    expect(prs).toHaveLength(2)
    expect(prs.map((p) => p.number)).toEqual([1, 7])
  })

  it('getAllRepos skips failing repos and records errors', async () => {
    const cache = createListCache({
      full: async (repo) => {
        if (repo === 'G-Eskayo/bad') throw new Error('404')
        return [{ number: 1, title: 'ok', repo }]
      },
      light: async (repo) => []
    }, 5 * 60_000)

    const { prs, errors } = await cache.getAllRepos([MARVIN_REPO, 'G-Eskayo/bad'])
    expect(prs).toHaveLength(1)
    expect(prs[0].repo).toBe(MARVIN_REPO)
    expect(errors).toHaveLength(1)
    expect(errors[0]).toMatchObject({ repo: 'G-Eskayo/bad' })
  })

  it('fresh: true bypasses the cache', async () => {
    let callCount = 0
    const cache = createListCache({
      full: async (repo) => {
        callCount++
        return []
      },
      light: async (repo) => []
    }, 5 * 60_000)

    await cache.getRepo(MARVIN_REPO)
    expect(callCount).toBe(1)

    await cache.getRepo(MARVIN_REPO)
    expect(callCount).toBe(1) // cached

    await cache.getRepo(MARVIN_REPO, { fresh: true })
    expect(callCount).toBe(2) // bypassed cache
  })
})
