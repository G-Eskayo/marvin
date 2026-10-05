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
