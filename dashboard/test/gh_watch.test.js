import { describe, it, expect, vi } from 'vitest'
import { createChangeDetector, createGithubProbe, issuesEndpoint, createHeadWatcher, createHeadProbe, prHeadEndpoint, headSha } from '../webhook-server/gh_watch.js'

const probeFrom = (script) => {
  const calls = []
  const probe = vi.fn(async (repo, etag) => {
    calls.push({ repo, etag })
    return script.shift()
  })
  return { probe, calls }
}

// What the probe answers on a 200: the newest issue, as GitHub lists it (only the fields the detector reads).
const top = (etag, number, updated_at) => ({ status: 200, etag, body: [{ number, updated_at }] })

describe('createChangeDetector', () => {
  it('records the first answer silently, then fires only when the newest issue changes', async () => {
    const { probe, calls } = probeFrom([top('a', 7, 't1'), { status: 304 }, top('b', 7, 't2')])
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

  // marvin#603: on 2026-10-22 GitHub sent a new ETag on every 200 for four hours while nothing changed, and every
  // repo "changed" on every tick. The ETag only buys free 304s; what changed is decided from the content.
  it('does not fire when a 200 brings a new etag but the same newest issue', async () => {
    const { probe, calls } = probeFrom([top('a', 7, 't1'), top('b', 7, 't1'), top('c', 7, 't1'), { status: 304 }])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    for (let i = 0; i < 4; i++) await d.tick(['o/r'])
    expect(onChange).not.toHaveBeenCalled()
    expect(calls.map((c) => c.etag)).toEqual([undefined, 'a', 'b', 'c']) // still sends the newest etag, for the 304
  })

  it('fires when the newest issue was updated, even under the same etag', async () => {
    const { probe } = probeFrom([top('a', 7, 't1'), top('a', 7, 't2')])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/r'])
    await d.tick(['o/r'])
    expect(onChange.mock.calls).toEqual([['o/r']])
  })

  it('fires when a different issue becomes the newest, even with the same updated_at', async () => {
    const { probe } = probeFrom([top('a', 7, 't1'), top('b', 8, 't1')])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/r'])
    await d.tick(['o/r'])
    expect(onChange.mock.calls).toEqual([['o/r']])
  })

  it('fires once per change, not again on the next identical 200', async () => {
    const { probe } = probeFrom([top('a', 7, 't1'), top('b', 7, 't2'), top('c', 7, 't2')])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    for (let i = 0; i < 3; i++) await d.tick(['o/r'])
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('treats an empty repo getting its first issue as a change, and staying empty as none', async () => {
    const { probe } = probeFrom([{ status: 200, etag: 'a', body: [] }, { status: 200, etag: 'b', body: [] }, top('c', 1, 't1')])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    for (let i = 0; i < 3; i++) await d.tick(['o/r'])
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('ignores a 200 whose body is not an issue list, and keeps its last state', async () => {
    const { probe, calls } = probeFrom([top('a', 7, 't1'), { status: 200, etag: 'b', body: { message: 'odd' } }, { status: 200, etag: 'c' }, top('d', 7, 't1')])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    for (let i = 0; i < 4; i++) await d.tick(['o/r'])
    expect(onChange).not.toHaveBeenCalled()
    expect(calls.map((c) => c.etag)).toEqual([undefined, 'a', 'a', 'a'])
  })

  it('ignores non-200 answers (rate limit, server error) without losing state', async () => {
    const { probe } = probeFrom([top('a', 7, 't1'), { status: 403 }, { status: 502 }, top('b', 7, 't1')])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    for (let i = 0; i < 4; i++) await d.tick(['o/r'])
    expect(onChange).not.toHaveBeenCalled()
  })

  it('tracks each repo separately', async () => {
    const { probe } = probeFrom([top('x', 1, 't1'), top('y', 2, 't1'), top('x2', 1, 't2'), { status: 304 }])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/a', 'o/b'])
    await d.tick(['o/a', 'o/b'])
    expect(onChange.mock.calls).toEqual([['o/a']])
  })

  it('ignores probe failures and keeps its last state', async () => {
    const answers = [async () => top('a', 7, 't1'), async () => { throw new Error('offline') }, async () => ({ status: 304 }), async () => top('b', 7, 't1')]
    const probe = vi.fn((repo, etag) => answers.shift()(repo, etag))
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/r'])
    await expect(d.tick(['o/r'])).resolves.toBe(0) // a throwing probe resolves (0 repos answered), never rejects
    await d.tick(['o/r'])
    await d.tick(['o/r'])
    expect(onChange).not.toHaveBeenCalled()
    expect(probe.mock.calls[2][1]).toBe('a')
  })

  it('still fires for a real change that arrives after a failure', async () => {
    const answers = [async () => top('a', 7, 't1'), async () => { throw new Error('offline') }, async () => top('b', 7, 't2')]
    const probe = vi.fn((repo, etag) => answers.shift()(repo, etag))
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    for (let i = 0; i < 3; i++) await d.tick(['o/r'])
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('forgets repos that left the registry', async () => {
    const { probe, calls } = probeFrom([top('a', 7, 't1'), top('b', 7, 't2')])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/r'])
    await d.tick([])
    await d.tick(['o/r']) // re-added: treated as first sight again, not a change
    expect(onChange).not.toHaveBeenCalled()
    expect(calls[1].etag).toBeUndefined() // and its old etag was dropped with it
  })
})

describe('createGithubProbe', () => {
  const fakeFetch = (status, etag, body) => vi.fn(async () => ({ status, headers: { get: (h) => (h === 'etag' ? etag : null) }, json: async () => body }))

  it('sends the etag conditionally and returns the body on a 200', async () => {
    const doFetch = fakeFetch(200, 'W/"e2"', [{ number: 3, updated_at: 't' }])
    const res = await createGithubProbe({ GH_TOKEN: 'tok' }, doFetch)('o/r', 'W/"e1"')
    expect(doFetch.mock.calls[0][0]).toBe(issuesEndpoint('o/r'))
    expect(doFetch.mock.calls[0][1].headers['If-None-Match']).toBe('W/"e1"')
    expect(doFetch.mock.calls[0][1].headers.Authorization).toBe('Bearer tok')
    expect(res).toEqual({ status: 200, etag: 'W/"e2"', body: [{ number: 3, updated_at: 't' }] })
  })

  it('does not read a body on a 304', async () => {
    const doFetch = fakeFetch(304, null, undefined)
    const json = vi.fn()
    doFetch.mockImplementation(async () => ({ status: 304, headers: { get: () => null }, json }))
    const res = await createGithubProbe({}, doFetch)('o/r', 'W/"e1"')
    expect(res).toEqual({ status: 304, etag: undefined })
    expect(json).not.toHaveBeenCalled()
  })
})

describe('issuesEndpoint', () => {
  it('asks for only the most recently updated item, any state', () => {
    expect(issuesEndpoint('o/r')).toBe('https://api.github.com/repos/o/r/issues?state=all&sort=updated&direction=desc&per_page=1')
  })
})

describe('createHeadWatcher', () => {
  const prHeadFrom = (script) => {
    const calls = []
    const probe = vi.fn(async ({ repo, number, etag }) => {
      calls.push({ repo, number, etag })
      return script.shift()
    })
    return { probe, calls }
  }

  const prHead = (etag, sha) => ({ status: 200, etag, body: { head: { sha } } })

  it('records the first answer silently, then fires only when the head sha changes', async () => {
    const { probe, calls } = prHeadFrom([prHead('a', 'sha1'), { status: 304 }, prHead('b', 'sha2')])
    const onChange = vi.fn()
    const w = createHeadWatcher({ probe, onChange })
    await w.tick([{ repo: 'o/r', number: 1 }])
    expect(onChange).not.toHaveBeenCalled()
    await w.tick([{ repo: 'o/r', number: 1 }])
    expect(onChange).not.toHaveBeenCalled()
    await w.tick([{ repo: 'o/r', number: 1 }])
    expect(onChange).toHaveBeenCalledWith({ repo: 'o/r', number: 1, head: null })
    expect(calls.map((c) => c.etag)).toEqual([undefined, 'a', 'a'])
  })

  it('fires on the first probe when watching for a specific head that differs from the current head', async () => {
    const { probe } = prHeadFrom([prHead('a', 'sha1')])
    const onChange = vi.fn()
    const w = createHeadWatcher({ probe, onChange })
    // Watch for a specific head 'old-head', but the current head is 'sha1' — should fire on first probe
    await w.tick([{ repo: 'o/r', number: 1, head: 'old-head' }])
    expect(onChange).toHaveBeenCalledWith({ repo: 'o/r', number: 1, head: 'old-head' })
  })

  it('fires when moving away from the watched head', async () => {
    const { probe } = prHeadFrom([prHead('a', 'sha1'), prHead('b', 'sha2')])
    const onChange = vi.fn()
    const w = createHeadWatcher({ probe, onChange })
    // Start watching the current head 'sha1' as the watched head
    await w.tick([{ repo: 'o/r', number: 1, head: 'sha1' }])
    expect(onChange).not.toHaveBeenCalled() // No change on first tick
    // Now the head changes to 'sha2' — should fire because we've moved away from the watched head
    await w.tick([{ repo: 'o/r', number: 1, head: 'sha1' }])
    expect(onChange).toHaveBeenCalledWith({ repo: 'o/r', number: 1, head: 'sha1' })
  })

  it('does not fire when a 200 brings a new etag but the same head sha', async () => {
    const { probe } = prHeadFrom([prHead('a', 'sha1'), prHead('b', 'sha1'), prHead('c', 'sha1'), { status: 304 }])
    const onChange = vi.fn()
    const w = createHeadWatcher({ probe, onChange })
    for (let i = 0; i < 4; i++) await w.tick([{ repo: 'o/r', number: 1 }])
    expect(onChange).not.toHaveBeenCalled()
  })

  it('fires once per change, not again on the next identical 200', async () => {
    const { probe } = prHeadFrom([prHead('a', 'sha1'), prHead('b', 'sha2'), prHead('c', 'sha2')])
    const onChange = vi.fn()
    const w = createHeadWatcher({ probe, onChange })
    for (let i = 0; i < 3; i++) await w.tick([{ repo: 'o/r', number: 1 }])
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('ignores non-200 answers and keeps its last state', async () => {
    const { probe } = prHeadFrom([prHead('a', 'sha1'), { status: 403 }, { status: 502 }, prHead('b', 'sha1')])
    const onChange = vi.fn()
    const w = createHeadWatcher({ probe, onChange })
    for (let i = 0; i < 4; i++) await w.tick([{ repo: 'o/r', number: 1 }])
    expect(onChange).not.toHaveBeenCalled()
  })

  it('tracks each PR separately', async () => {
    const { probe } = prHeadFrom([prHead('x', 'sha1'), prHead('y', 'sha2'), prHead('x2', 'sha2'), { status: 304 }])
    const onChange = vi.fn()
    const w = createHeadWatcher({ probe, onChange })
    await w.tick([{ repo: 'o/r', number: 1 }, { repo: 'o/s', number: 2 }])
    await w.tick([{ repo: 'o/r', number: 1 }, { repo: 'o/s', number: 2 }])
    expect(onChange.mock.calls).toEqual([[{ repo: 'o/r', number: 1, head: null }]])
  })

  it('ignores probe failures and keeps its last state', async () => {
    const answers = [async () => prHead('a', 'sha1'), async () => { throw new Error('offline') }, async () => ({ status: 304 }), async () => prHead('b', 'sha2')]
    const probe = vi.fn((obj) => answers.shift()(obj))
    const onChange = vi.fn()
    const w = createHeadWatcher({ probe, onChange })
    await w.tick([{ repo: 'o/r', number: 1 }])
    await expect(w.tick([{ repo: 'o/r', number: 1 }])).resolves.toBeUndefined()
    await w.tick([{ repo: 'o/r', number: 1 }])
    await w.tick([{ repo: 'o/r', number: 1 }])
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('forgets PRs that left the candidate list', async () => {
    const { probe, calls } = prHeadFrom([prHead('a', 'sha1'), prHead('b', 'sha2')])
    const onChange = vi.fn()
    const w = createHeadWatcher({ probe, onChange })
    await w.tick([{ repo: 'o/r', number: 1 }])
    await w.tick([])
    await w.tick([{ repo: 'o/r', number: 1 }])
    expect(onChange).not.toHaveBeenCalled()
    expect(calls[1].etag).toBeUndefined()
  })
})

describe('createHeadProbe', () => {
  const fakeFetch = (status, etag, body) => vi.fn(async () => ({ status, headers: { get: (h) => (h === 'etag' ? etag : null) }, json: async () => body }))

  it('sends the etag conditionally and returns the body on a 200', async () => {
    const doFetch = fakeFetch(200, 'W/"e2"', { head: { sha: 'abc123' } })
    const res = await createHeadProbe({ GH_TOKEN: 'tok' }, doFetch)({ repo: 'o/r', number: 42, etag: 'W/"e1"' })
    expect(doFetch.mock.calls[0][0]).toBe(prHeadEndpoint('o/r', 42))
    expect(doFetch.mock.calls[0][1].headers['If-None-Match']).toBe('W/"e1"')
    expect(doFetch.mock.calls[0][1].headers.Authorization).toBe('Bearer tok')
    expect(res).toEqual({ status: 200, etag: 'W/"e2"', body: { head: { sha: 'abc123' } } })
  })

  it('does not read a body on a 304', async () => {
    const doFetch = fakeFetch(304, null, undefined)
    const json = vi.fn()
    doFetch.mockImplementation(async () => ({ status: 304, headers: { get: () => null }, json }))
    const res = await createHeadProbe({}, doFetch)({ repo: 'o/r', number: 42, etag: 'W/"e1"' })
    expect(res).toEqual({ status: 304, etag: undefined })
    expect(json).not.toHaveBeenCalled()
  })
})

describe('headSha', () => {
  it('extracts the sha from a PR head', () => {
    expect(headSha({ head: { sha: 'abc123' } })).toBe('abc123')
  })

  it('returns undefined for a missing or invalid body', () => {
    expect(headSha(null)).toBeUndefined()
    expect(headSha({})).toBeUndefined()
    expect(headSha({ head: null })).toBeUndefined()
    expect(headSha({ head: {} })).toBeUndefined()
  })
})

describe('prHeadEndpoint', () => {
  it('builds the correct endpoint URL', () => {
    expect(prHeadEndpoint('o/r', 42)).toBe('https://api.github.com/repos/o/r/pulls/42')
  })
})
