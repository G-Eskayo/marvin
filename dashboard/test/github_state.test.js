import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { createGithubState, repoOfSource, gateCooldownUntil } from '../electron/main/github_state.js'

// The real gate's state on this Mac must never decide a test.
process.env.MARVIN_GH_GATE_STATE = '/nonexistent/gh-gate.json'

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

  it('when GitHub refuses, the last known state is shown instead of an error, and retried after a short wait', async () => {
    let t = 0
    const s = createGithubState({ now: () => t })
    await s.get('prs', 'o/a', async () => 'known')
    s.changed('o/a')
    expect(await s.get('prs', 'o/a', async () => { throw new Error('API rate limit') })).toBe('known')
    t += 61_000
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

  // #323: while GitHub refuses, back off instead of asking again on every screen refresh.
  it('after a failure it waits before asking again, and serves what it last knew meanwhile', async () => {
    let t = 0, n = 0, fail = false
    const s = createGithubState({ now: () => t, cooldownUntil: () => 0 })
    const fetch = async () => { n++; if (fail) throw new Error('rate limit'); return `v${n}` }
    expect(await s.get('prs', 'o/a', fetch)).toBe('v1')
    s.changed('o/a'); fail = true
    expect(await s.get('prs', 'o/a', fetch)).toBe('v1')        // refused: last value
    for (let i = 0; i < 50; i++) await s.get('prs', 'o/a', fetch)  // 50 refreshes inside the back-off
    expect(n).toBe(2)
    t += 61_000
    await s.get('prs', 'o/a', fetch)                             // back-off over: one more try, fails again
    expect(n).toBe(3)
    t += 61_000
    await s.get('prs', 'o/a', fetch)                             // doubled: still waiting at 61 s
    expect(n).toBe(3)
    t += 60_000; fail = false
    expect(await s.get('prs', 'o/a', fetch)).toBe('v4')          // 2 min later it recovers
  })

  it('with nothing known yet, a back-off answers with the last error at once, without calling', async () => {
    let n = 0
    const s = createGithubState({ now: () => 0, cooldownUntil: () => 0 })
    const fetch = async () => { n++; throw new Error('rate limit') }
    await expect(s.get('prs', 'o/a', fetch)).rejects.toThrow('rate limit')
    await expect(s.get('prs', 'o/a', fetch)).rejects.toThrow('rate limit')
    expect(n).toBe(1)
  })

  it("honours the GitHub gate's cooldown, and a fresh read still goes through", async () => {
    let n = 0, cooling = 0
    const s = createGithubState({ now: () => 0, cooldownUntil: () => cooling })
    const fetch = async () => { n++; return `v${n}` }
    await s.get('prs', 'o/a', fetch)
    s.changed('o/a'); cooling = 10 * 60_000
    await s.get('prs', 'o/a', fetch)
    expect(n).toBe(1)                                            // gate cooling down: no call
    await s.get('prs', 'o/a', fetch, { fresh: true })
    expect(n).toBe(2)                                            // a merge or explicit refresh still reads
  })

  // #324: a view spanning every repo re-reads at most every few minutes, however many change pings arrive.
  it('reads the cooldown the gate writes, and treats a missing file as none', () => {
    const dir = mkdtempSync(join(tmpdir(), 'gate-'))
    writeFileSync(join(dir, 'gh-gate.json'), JSON.stringify({ cooldown_until: 1791511143 }))
    expect(gateCooldownUntil(join(dir, 'gh-gate.json'))).toBe(1791511143000)
    expect(gateCooldownUntil(join(dir, 'missing.json'))).toBe(0)
  })

  it('minIntervalMs limits how often a changed value is re-read', async () => {
    let t = 0
    const s = createGithubState({ now: () => t, cooldownUntil: () => 0 })
    const { calls, fetch } = counter()
    await s.get('rework', null, fetch('r'), { minIntervalMs: 5 * 60_000 })
    for (let i = 0; i < 10; i++) { s.changed(`o/${i}`); t += 20_000; await s.get('rework', null, fetch('r'), { minIntervalMs: 5 * 60_000 }) }
    expect(calls).toEqual(['r'])                                 // 10 pings in 200 s: no re-read
    t += 120_000
    await s.get('rework', null, fetch('r'), { minIntervalMs: 5 * 60_000 })
    expect(calls).toEqual(['r', 'r'])
  })
})
