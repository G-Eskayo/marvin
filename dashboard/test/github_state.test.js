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

  // marvin#555: MR Review says "Last checked 20 s ago", so the time of the last real read must reach the screen; and the
  // check watch reads which commits to watch from what is already in memory, without asking GitHub.
  it('fetchedAt: when a value was last read from GitHub (not when it was last served from memory)', async () => {
    let t = 1000
    const s = createGithubState({ now: () => t })
    const { fetch } = counter()
    expect(s.fetchedAt('prs', 'o/a')).toBe(null)
    await s.get('prs', 'o/a', fetch('a'))
    t = 5000
    await s.get('prs', 'o/a', fetch('a'))
    expect(s.fetchedAt('prs', 'o/a')).toBe(1000)
    s.changed('o/a')
    await s.get('prs', 'o/a', fetch('a'))
    expect(s.fetchedAt('prs', 'o/a')).toBe(5000)
    expect(s.fetchedAt('prs-light', 'o/a')).toBe(null)
  })

  it('fetchedAt keeps the old time when a re-read fails (the screen must not claim a fresh look)', async () => {
    let t = 1000
    const s = createGithubState({ now: () => t, cooldownUntil: () => 0 })
    await s.get('prs', 'o/a', async () => ['x'])
    s.changed('o/a')
    t = 9000
    expect(await s.get('prs', 'o/a', async () => { throw new Error('offline') })).toEqual(['x'])
    expect(s.fetchedAt('prs', 'o/a')).toBe(1000)
  })

  it("peek: every repo's last-known value of one kind, without reading GitHub", async () => {
    const s = createGithubState({ now: () => 0 })
    expect(s.peek('prs')).toEqual([])
    await s.get('prs', 'o/a', async () => [1])
    await s.get('prs', 'o/b', async () => [2])
    await s.get('board', 'o/a', async () => 'board')
    s.get('prs', 'o/c', () => new Promise(() => {})) // still in flight: nothing known yet
    expect(s.peek('prs')).toEqual([{ repo: 'o/a', value: [1] }, { repo: 'o/b', value: [2] }])
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

// Local-first actions (CONTEXT.md "Dashboard actions render their true result locally at once"): a write the dashboard
// made is applied to its memory at once, from GitHub's own answer to the write, and a re-read that was already on its
// way (it left before the write) must not put the old state back.
describe('createGithubState.patch: apply what the dashboard just wrote', () => {
  const deferred = () => { let resolve; const p = new Promise((r) => (resolve = r)); return { p, resolve } }

  it('changes the remembered value in place, without a GitHub read or invalidating the repo', async () => {
    const s = createGithubState({ now: () => 0 })
    const { calls, fetch } = counter({ a: [{ number: 1, body: 'old' }] })
    await s.get('prs', 'o/a', fetch('a'))
    expect(s.patch('prs', 'o/a', (list) => list.map((p) => ({ ...p, body: 'new' })))).toBe(true)
    expect(await s.get('prs', 'o/a', fetch('a'))).toEqual([{ number: 1, body: 'new' }])
    expect(calls).toEqual(['a'])
  })

  it('a slow re-read that left before the write arrives after it: the newer local state survives', async () => {
    const s = createGithubState({ now: () => 0 })
    await s.get('prs', 'o/a', async () => [{ number: 1, body: 'old' }])
    const slow = deferred()
    const reading = s.get('prs', 'o/a', () => slow.p, { fresh: true })
    s.patch('prs', 'o/a', (list) => list.map((p) => (p.number === 1 ? { ...p, body: 'answered' } : p)))
    slow.resolve([{ number: 1, body: 'old' }, { number: 2, body: 'a new PR' }]) // GitHub's answer from before the write
    const got = await reading
    expect(got).toEqual([{ number: 1, body: 'answered' }, { number: 2, body: 'a new PR' }])
    expect(await s.get('prs', 'o/a', async () => { throw new Error('must not read') })).toEqual(got)
  })

  it('a re-read that starts after the write is GitHub\'s word and replaces the local value', async () => {
    const s = createGithubState({ now: () => 0 })
    await s.get('prs', 'o/a', async () => [{ number: 1, body: 'old' }])
    s.patch('prs', 'o/a', (list) => list.map((p) => ({ ...p, body: 'answered' })))
    expect(await s.get('prs', 'o/a', async () => [{ number: 1, body: 'github says otherwise' }], { fresh: true })).toEqual([{ number: 1, body: 'github says otherwise' }])
  })

  it('a write while the first read is still on its way (nothing remembered yet) is applied when it lands', async () => {
    const s = createGithubState({ now: () => 0 })
    const slow = deferred()
    const reading = s.get('prs', 'o/a', () => slow.p)
    expect(s.patch('prs', 'o/a', (list) => list.filter((p) => p.number !== 1))).toBe(false)
    slow.resolve([{ number: 1 }, { number: 2 }])
    expect(await reading).toEqual([{ number: 2 }])
  })

  it('nothing remembered and nothing on its way: a patch is a no-op, and the next read asks GitHub', async () => {
    const s = createGithubState({ now: () => 0 })
    expect(s.patch('prs', 'o/a', () => { throw new Error('not called') })).toBe(false)
    expect(await s.get('prs', 'o/a', async () => ['fresh'])).toEqual(['fresh'])
  })

  it('a patch that throws leaves the remembered value as it was', async () => {
    const s = createGithubState({ now: () => 0 })
    await s.get('prs', 'o/a', async () => ['kept'])
    expect(() => s.patch('prs', 'o/a', () => { throw new Error('bad patch') })).toThrow('bad patch')
    expect(await s.get('prs', 'o/a', async () => ['x'])).toEqual(['kept'])
  })

  it('a failed re-read keeps the patched value, not the one from before the write', async () => {
    const s = createGithubState({ now: () => 0 })
    await s.get('prs', 'o/a', async () => ['old'])
    const slow = deferred()
    const reading = s.get('prs', 'o/a', () => slow.p, { fresh: true })
    s.patch('prs', 'o/a', () => ['answered'])
    slow.resolve(Promise.reject(new Error('offline')))
    expect(await reading).toEqual(['answered'])
  })

  it('counts local writes, so a coalesced reader can tell its answer is older than a write', () => {
    const s = createGithubState({ now: () => 0 })
    const before = s.localSeq()
    s.patch('prs', 'o/a', (v) => v)
    expect(s.localSeq()).toBe(before + 1)
  })
})
