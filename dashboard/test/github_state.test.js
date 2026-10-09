import { describe, it, expect } from 'vitest'
import { createGithubState, repoOfSource } from '../electron/main/github_state.js'

function counter(values = {}) {
  const calls = []
  const fetch = (key) => async () => { calls.push(key); return values[key] ?? `${key}#${calls.length}` }
  return { calls, fetch }
}

describe('createGithubState: the last-known GitHub state, re-read only when GitHub says it changed', () => {
  it('serves repeat reads from memory: tab switches and polls cost nothing', async () => {
    let t = 0
    const s = createGithubState({ now: () => t })
    const { calls, fetch } = counter()
    await s.get('prs', 'o/a', fetch('a'))
    t += 25 * 60_000
    await s.get('prs', 'o/a', fetch('a'))
    expect(calls).toEqual(['a'])
  })

  it('a change re-reads only the repo that changed', async () => {
    const s = createGithubState({ now: () => 0 })
    const { calls, fetch } = counter()
    await s.get('prs', 'o/a', fetch('a'))
    await s.get('prs', 'o/b', fetch('b'))
    s.changed('o/a')
    await s.get('prs', 'o/a', fetch('a'))
    await s.get('prs', 'o/b', fetch('b'))
    expect(calls).toEqual(['a', 'b', 'a'])
  })

  it('values that span every repo (repo null) re-read after a change anywhere', async () => {
    const s = createGithubState({ now: () => 0 })
    const { calls, fetch } = counter()
    await s.get('queue', null, fetch('q'))
    await s.get('queue', null, fetch('q'))
    s.changed('o/z')
    await s.get('queue', null, fetch('q'))
    expect(calls).toEqual(['q', 'q'])
  })

  it('a safety refresh after 30 minutes, or a per-key one', async () => {
    let t = 0
    const s = createGithubState({ now: () => t })
    const { calls, fetch } = counter()
    await s.get('prs', 'o/a', fetch('a'))
    await s.get('rework', null, fetch('r'), { safetyMs: 60_000 })
    t += 61_000
    await s.get('rework', null, fetch('r'), { safetyMs: 60_000 })
    await s.get('prs', 'o/a', fetch('a'))
    t += 30 * 60_000
    await s.get('prs', 'o/a', fetch('a'))
    expect(calls).toEqual(['a', 'r', 'r', 'a'])
  })

  it('fresh forces a re-read (a merge must not act on old data)', async () => {
    const s = createGithubState({ now: () => 0 })
    const { calls, fetch } = counter()
    await s.get('prs', 'o/a', fetch('a'))
    await s.get('prs', 'o/a', fetch('a'), { fresh: true })
    expect(calls).toEqual(['a', 'a'])
  })

  it('concurrent reads share one GitHub call', async () => {
    const s = createGithubState({ now: () => 0 })
    const { calls, fetch } = counter()
    await Promise.all([s.get('prs', 'o/a', fetch('a')), s.get('prs', 'o/a', fetch('a')), s.get('prs', 'o/a', fetch('a'))])
    expect(calls).toEqual(['a'])
  })

  it('a change during a read leaves the result marked stale', async () => {
    const s = createGithubState({ now: () => 0 })
    let release
    const slow = () => new Promise((r) => { release = r })
    const p = s.get('prs', 'o/a', slow)
    s.changed('o/a')
    release('old')
    expect(await p).toBe('old')
    const { calls, fetch } = counter()
    await s.get('prs', 'o/a', fetch('a'))
    expect(calls).toEqual(['a'])
  })

  it('when GitHub refuses, the last known state is shown instead of an error, and retried next time', async () => {
    const s = createGithubState({ now: () => 0 })
    await s.get('prs', 'o/a', async () => 'known')
    s.changed('o/a')
    expect(await s.get('prs', 'o/a', async () => { throw new Error('API rate limit') })).toBe('known')
    expect(await s.get('prs', 'o/a', async () => 'new')).toBe('new')
  })

  it('with nothing known yet, a failure still throws so the caller can say so', async () => {
    const s = createGithubState({ now: () => 0 })
    await expect(s.get('prs', 'o/a', async () => { throw new Error('offline') })).rejects.toThrow('offline')
  })

  it('changedAll re-reads everything; stats say how often memory answered', async () => {
    const s = createGithubState({ now: () => 0 })
    const { calls, fetch } = counter()
    await s.get('prs', 'o/a', fetch('a'))
    await s.get('prs', 'o/a', fetch('a'))
    s.changedAll()
    await s.get('prs', 'o/a', fetch('a'))
    expect(calls).toEqual(['a', 'a'])
    expect(s.stats()).toMatchObject({ hits: 1, reads: 2 })
  })
})

describe('repoOfSource', () => {
  it('reads the repo from a change-watch ping source', () => {
    expect(repoOfSource('github:G-Eskayo/marvin')).toBe('G-Eskayo/marvin')
    expect(repoOfSource('ping')).toBe(null)
    expect(repoOfSource(undefined)).toBe(null)
  })
})
