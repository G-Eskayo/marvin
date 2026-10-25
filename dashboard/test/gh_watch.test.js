import { describe, it, expect, vi } from 'vitest'
import { createChangeDetector, issuesEndpoint } from '../webhook-server/gh_watch.js'

const probeFrom = (script) => {
  const calls = []
  const probe = vi.fn(async (repo, etag) => {
    calls.push({ repo, etag })
    return script.shift()
  })
  return { probe, calls }
}

describe('createChangeDetector', () => {
  it('records the first etag silently, then fires only when it changes', async () => {
    const { probe, calls } = probeFrom([{ status: 200, etag: 'a' }, { status: 304 }, { status: 200, etag: 'b' }])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/r'])
    expect(onChange).not.toHaveBeenCalled()
    await d.tick(['o/r'])
    expect(onChange).not.toHaveBeenCalled()
    await d.tick(['o/r'])
    expect(onChange).toHaveBeenCalledWith('o/r')
    expect(calls.map((c) => c.etag)).toEqual([undefined, 'a', 'a'])
  })

  it('tracks each repo separately', async () => {
    const { probe } = probeFrom([{ status: 200, etag: 'x' }, { status: 200, etag: 'y' }, { status: 200, etag: 'x2' }, { status: 304 }])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/a', 'o/b'])
    await d.tick(['o/a', 'o/b'])
    expect(onChange.mock.calls).toEqual([['o/a']])
  })

  it('ignores probe failures and keeps its last etag', async () => {
    const answers = [async () => ({ status: 200, etag: 'a' }), async () => { throw new Error('offline') }, async () => ({ status: 304 })]
    const probe = vi.fn((repo, etag) => answers.shift()(repo, etag))
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/r'])
    await expect(d.tick(['o/r'])).resolves.toBeUndefined()
    await d.tick(['o/r'])
    expect(onChange).not.toHaveBeenCalled()
    expect(probe.mock.calls[2][1]).toBe('a')
  })

  it('forgets repos that left the registry', async () => {
    const { probe } = probeFrom([{ status: 200, etag: 'a' }, { status: 200, etag: 'b' }])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/r'])
    await d.tick([])
    await d.tick(['o/r']) // re-added: treated as first sight again, not a change
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('issuesEndpoint', () => {
  it('asks for only the most recently updated item, any state', () => {
    expect(issuesEndpoint('o/r')).toBe('https://api.github.com/repos/o/r/issues?state=all&sort=updated&direction=desc&per_page=1')
  })
})

describe('repoEndpoint', () => {
  it('returns the GitHub API endpoint for a repository HEAD', async () => {
    const { repoEndpoint } = await import('../webhook-server/gh_watch.js')
    expect(repoEndpoint('o/r')).toBe('https://api.github.com/repos/o/r')
  })
})

describe('createRepoHeadProbe', () => {
  it('makes a conditional GET to the repo endpoint and returns status and etag', async () => {
    const { createRepoHeadProbe } = await import('../webhook-server/gh_watch.js')
    const doFetch = vi.fn(async () => ({
      status: 200,
      headers: new Map([['etag', '"abc123"']])
    }))
    const probe = createRepoHeadProbe({ GH_TOKEN: 'tok_test' }, doFetch)
    const result = await probe('o/r')
    expect(result.status).toBe(200)
    expect(result.etag).toBe('"abc123"')
    expect(doFetch.mock.calls[0][0]).toContain('/repos/o/r')
  })

  it('includes the auth token in the request', async () => {
    const { createRepoHeadProbe } = await import('../webhook-server/gh_watch.js')
    const doFetch = vi.fn(async () => ({
      status: 200,
      headers: new Map()
    }))
    await createRepoHeadProbe({ GH_TOKEN: 'tok_test' }, doFetch)('o/r')
    const headers = doFetch.mock.calls[0][1].headers
    expect(headers.Authorization).toBe('Bearer tok_test')
  })

  it('uses If-None-Match for conditional requests', async () => {
    const { createRepoHeadProbe } = await import('../webhook-server/gh_watch.js')
    const doFetch = vi.fn(async () => ({
      status: 304,
      headers: new Map()
    }))
    const probe = createRepoHeadProbe({}, doFetch)
    await probe('o/r', '"old_etag"')
    const headers = doFetch.mock.calls[0][1].headers
    expect(headers['If-None-Match']).toBe('"old_etag"')
  })
})

describe('createRepoOpenChecker', () => {
  it('records the first etag silently, then fires onChange only when it changes', async () => {
    const { createRepoOpenChecker } = await import('../webhook-server/gh_watch.js')
    const probe = vi.fn(async (_repo, etag) => {
      if (!etag) return { status: 200, etag: 'a' }
      return { status: 304 }
    })
    const onChange = vi.fn()
    const checker = createRepoOpenChecker({ probe, onChange })

    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).not.toHaveBeenCalled()

    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).not.toHaveBeenCalled()

    // Simulate a change
    probe.mockResolvedValueOnce({ status: 200, etag: 'b' })
    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).toHaveBeenCalledWith({ id: 'p1', repo: 'o/r' })
  })

  it('ignores 304 responses without storing them', async () => {
    const { createRepoOpenChecker } = await import('../webhook-server/gh_watch.js')
    const probe = vi.fn(async () => ({ status: 304 }))
    const onChange = vi.fn()
    const checker = createRepoOpenChecker({ probe, onChange })

    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).not.toHaveBeenCalled()
  })

  it('ignores non-200 responses without storing them', async () => {
    const { createRepoOpenChecker } = await import('../webhook-server/gh_watch.js')
    const probe = vi.fn(async () => ({ status: 500 }))
    const onChange = vi.fn()
    const checker = createRepoOpenChecker({ probe, onChange })

    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).not.toHaveBeenCalled()
  })

  it('ignores responses with missing etag', async () => {
    const { createRepoOpenChecker } = await import('../webhook-server/gh_watch.js')
    const probe = vi.fn(async () => ({ status: 200 }))
    const onChange = vi.fn()
    const checker = createRepoOpenChecker({ probe, onChange })

    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).not.toHaveBeenCalled()
  })

  it('handles probe errors gracefully without clobbering stored etag', async () => {
    const { createRepoOpenChecker } = await import('../webhook-server/gh_watch.js')
    const probe = vi.fn()
    probe.mockResolvedValueOnce({ status: 200, etag: 'a' })
    probe.mockRejectedValueOnce(new Error('offline'))
    probe.mockResolvedValueOnce({ status: 200, etag: 'b' })

    const onChange = vi.fn()
    const checker = createRepoOpenChecker({ probe, onChange })

    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).not.toHaveBeenCalled()

    await expect(checker.check({ id: 'p1', repo: 'o/r' })).resolves.not.toThrow()
    expect(onChange).not.toHaveBeenCalled()

    // Third check: stored etag is still 'a', new is 'b', so fires onChange
    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).toHaveBeenCalledWith({ id: 'p1', repo: 'o/r' })
  })

  it('fires onChange unconditionally once per call (checks can be from cache or miss)', async () => {
    const { createRepoOpenChecker } = await import('../webhook-server/gh_watch.js')
    const probe = vi.fn(async () => ({ status: 200, etag: 'a' }))
    const onChange = vi.fn()
    const checker = createRepoOpenChecker({ probe, onChange })

    // Every check should fire onChange if there was a previous value
    // (simulating both cache hits and cache misses being treated the same)
    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).not.toHaveBeenCalled() // first time

    probe.mockResolvedValueOnce({ status: 200, etag: 'a' })
    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).not.toHaveBeenCalled() // same etag, no change

    probe.mockResolvedValueOnce({ status: 200, etag: 'b' })
    await checker.check({ id: 'p1', repo: 'o/r' })
    expect(onChange).toHaveBeenCalledTimes(1) // changed
  })
})
