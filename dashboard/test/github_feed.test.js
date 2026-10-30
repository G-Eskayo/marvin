import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync, utimesSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { isPullOnlyNode, readFeed, feedAge, feedStatus, createFeedSource, feedOnlyGh, FeedError, STALE_MS } from '../electron/main/github_feed.js'
import { plainCause, prFetchBanner } from '../src/lib/pr_fetch_status.js'

const MIN = 60_000
const REPO = 'G-Eskayo/marvin'

function feedFile(content, { mtimeMs } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'gh-feed-'))
  const p = join(dir, 'github-feed.json')
  writeFileSync(p, typeof content === 'string' ? content : JSON.stringify(content))
  if (mtimeMs) utimesSync(p, mtimeMs / 1000, mtimeMs / 1000)
  return p
}

const pr = (n, extra = {}) => ({ number: n, title: `PR ${n}`, url: `https://github.com/${REPO}/pull/${n}`, body: 'b', files: [], headRefOid: 'abc', ...extra })
const goodFeed = (now, extra = {}) => ({
  version: 1,
  host: 'mac-mini-1',
  alive_at: now - MIN,
  repos: { [REPO]: { prs: { at: now - 30 * MIN, value: [pr(1), pr(2)] }, board: { at: now - 30 * MIN, value: { issues: [{ number: 5 }], prs: [], holdComments: {} } } } },
  ...extra
})

describe('isPullOnlyNode: the same rule as machine_profile.pull_only()', () => {
  const registry = {
    'mac-mini-1': { accepts: ['general', 'macos'] },
    'mac-mini-2012': { accepts: ['security', 'test'] },
    'old-mac': {}
  }
  it('a registered device that takes no general work is pull-only', () => {
    expect(isPullOnlyNode({ deviceId: 'mac-mini-2012', registry, platform: 'linux', env: {} })).toBe(true)
  })
  it('a full node is not, and an entry predating `accepts` is a full node', () => {
    expect(isPullOnlyNode({ deviceId: 'mac-mini-1', registry, platform: 'darwin', env: {} })).toBe(false)
    expect(isPullOnlyNode({ deviceId: 'old-mac', registry, platform: 'darwin', env: {} })).toBe(false)
  })
  it('an unknown Linux machine is never trusted as a full node; an unknown Mac is', () => {
    expect(isPullOnlyNode({ deviceId: null, registry, platform: 'linux', env: {} })).toBe(true)
    expect(isPullOnlyNode({ deviceId: null, registry, platform: 'darwin', env: {} })).toBe(false)
  })
  it('a garbled accepts (not a list) is pull-only, and MARVIN_PULL_ONLY overrides both ways', () => {
    expect(isPullOnlyNode({ deviceId: 'x', registry: { x: { accepts: 'general' } }, platform: 'darwin', env: {} })).toBe(true)
    expect(isPullOnlyNode({ deviceId: 'mac-mini-1', registry, platform: 'darwin', env: { MARVIN_PULL_ONLY: '1' } })).toBe(true)
    expect(isPullOnlyNode({ deviceId: null, registry, platform: 'linux', env: { MARVIN_PULL_ONLY: '0' } })).toBe(false)
  })
})

describe('readFeed: a broken copy is reported, never thrown', () => {
  it('missing, empty, truncated, not JSON and wrong-shaped files all come back as no feed', () => {
    expect(readFeed('/nonexistent/github-feed.json').problem).toBe('missing')
    for (const bad of ['', '{"version":1,"repos":{', 'null', '[]', '{"repos":[]}', '"text"']) {
      const got = readFeed(feedFile(bad))
      expect(got.feed).toBeNull()
      expect(got.problem).toBe('unreadable')
    }
  })
})

describe('feedStatus: how old the box view is, and when the Mini stopped answering', () => {
  const now = 1_800_000_000_000
  it('fresh: the older of the copy and the Mini last look', () => {
    const s = feedStatus({ feed: goodFeed(now), copiedAt: now - 2 * MIN }, now)
    expect(s.state).toBe('fresh')
    expect(s.text).toBe('Read from the Mini, 2 min ago.')
  })
  it('the copy is current but the Mini stopped looking at GitHub (its watch died): stale, with the age', () => {
    const s = feedStatus({ feed: goodFeed(now, { alive_at: now - 3 * 60 * MIN }), copiedAt: now - MIN }, now)
    expect(s.state).toBe('stale')
    expect(s.text).toBe("The Mini isn't answering: GitHub data last read from it 3 h ago.")
  })
  it('the Mini is fine but the copy stopped (box timer, network): stale too', () => {
    expect(feedStatus({ feed: goodFeed(now), copiedAt: now - STALE_MS - MIN }, now).state).toBe('stale')
  })
  it('clock skew: a Mini clock ahead of the box never gives a negative age', () => {
    const got = { feed: goodFeed(now, { alive_at: now + 5 * MIN }), copiedAt: now + 1000 }
    expect(feedAge(got, now)).toBe(0)
    expect(feedStatus(got, now).text).toBe('Read from the Mini, just now.')
  })
  it('an expiry-style date in the past or a junk alive_at is not taken as fresh', () => {
    expect(feedStatus({ feed: goodFeed(now, { alive_at: 0 }), copiedAt: null }, now).state).toBe('stale')
    expect(feedStatus({ feed: goodFeed(now, { alive_at: 'soon' }), copiedAt: null }, now).state).toBe('stale')
  })
  it('no feed at all says so plainly', () => {
    expect(feedStatus({ feed: null }, now).text).toMatch(/^The Mini isn't answering/)
  })
  it('none of these lines read as "sign in again" to the MR banner', () => {
    for (const text of [
      feedStatus({ feed: null }, now).text,
      feedStatus({ feed: goodFeed(now, { alive_at: 0 }) }, now).text,
      new FeedError(`${REPO} isn't in the Mini's GitHub feed yet.`).message
    ]) {
      expect(plainCause(text)).not.toMatch(/sign-in/)
      expect(text).not.toMatch(/log ?in|auth|token|credential/i)
    }
  })
})

describe('createFeedSource: the box answers the MR list and boards from the copy', () => {
  const now = 1_800_000_000_000
  it('serves the full list and the light cut of it, and the board', () => {
    const src = createFeedSource({ path: feedFile(goodFeed(now), { mtimeMs: now - MIN }), now: () => now })
    expect(src.openPrs(REPO).map((p) => p.number)).toEqual([1, 2])
    expect(src.openPrs(REPO, { light: true })[0]).toEqual({ number: 1, title: 'PR 1', url: `https://github.com/${REPO}/pull/1` })
    expect(src.board(REPO).issues).toEqual([{ number: 5 }])
    expect(src.readAt(REPO)).toBe(now - 30 * MIN)
    expect(src.status().state).toBe('fresh')
  })
  it('a repo the Mini does not carry fails alone, with a FeedError naming it', () => {
    const src = createFeedSource({ path: feedFile(goodFeed(now)), now: () => now })
    expect(() => src.openPrs('G-Eskayo/other')).toThrow(FeedError)
    expect(() => src.openPrs('G-Eskayo/other')).toThrow(/G-Eskayo\/other isn't in the Mini's GitHub feed/)
    expect(src.openPrs(REPO)).toHaveLength(2)
  })
  it('a wrong-shaped entry (prs not a list, board without issues) is a FeedError, not a crash downstream', () => {
    const f = goodFeed(now)
    f.repos[REPO].prs.value = { oops: 1 }
    f.repos[REPO].board.value = { prs: [] }
    const src = createFeedSource({ path: feedFile(f), now: () => now })
    expect(() => src.openPrs(REPO)).toThrow(FeedError)
    expect(() => src.board(REPO)).toThrow(FeedError)
  })
  it('a missing copy throws the "isn\'t answering" line, then picks the file up once it arrives', () => {
    const dir = mkdtempSync(join(tmpdir(), 'gh-feed-'))
    const p = join(dir, 'github-feed.json')
    const src = createFeedSource({ path: p, now: () => now })
    expect(() => src.openPrs(REPO)).toThrow(/The Mini isn't answering/)
    writeFileSync(p, JSON.stringify(goodFeed(now)))
    expect(src.openPrs(REPO)).toHaveLength(2)
    rmSync(p)
    expect(() => src.openPrs(REPO)).toThrow(FeedError)
  })
  it('re-reads only when the copy changes (mtime), so the 2-minute status dot costs one stat', () => {
    let reads = 0
    let m = 1
    const text = JSON.stringify(goodFeed(now))
    const src = createFeedSource({ path: '/x', now: () => now, read: () => { reads += 1; return text }, mtime: () => m })
    src.openPrs(REPO); src.openPrs(REPO); src.board(REPO)
    expect(reads).toBe(1)
    m = 2
    src.openPrs(REPO)
    expect(reads).toBe(2)
  })
})

describe('feedOnlyGh and the MR banner on the box', () => {
  it('anything the feed does not carry is refused plainly, with no login wording', async () => {
    await expect(feedOnlyGh(['issue', 'view', '5'])).rejects.toThrow(FeedError)
    await expect(feedOnlyGh(['pr', 'merge', 'x'])).rejects.toThrow(/reads GitHub only through the Mini \(asked: gh pr merge\)/)
    await expect(feedOnlyGh([])).rejects.not.toThrow(/auth|log ?in/i)
  })
  it('a fresh feed shows a quiet "Read from the Mini" line, a stale one an amber banner with the age', () => {
    const now = 1_800_000_000_000
    const fresh = prFetchBanner({ errors: [], projects: 1, lastGoodAt: now, source: { from: 'mini', state: 'fresh', text: 'Read from the Mini, 2 min ago.' } }, now)
    expect(fresh).toEqual({ tone: 'info', text: 'Read from the Mini, 2 min ago.' })
    const stale = prFetchBanner({ errors: [], projects: 1, lastGoodAt: now, source: { from: 'mini', state: 'stale', text: "The Mini isn't answering: GitHub data last read from it 3 h ago." } }, now)
    expect(stale.tone).toBe('amber')
    expect(stale.text).toMatch(/^The Mini isn't answering/)
    const missing = prFetchBanner({ errors: [{ repo: REPO, message: "The Mini isn't answering: no GitHub data from it yet on this machine." }], projects: 1, lastGoodAt: null, source: { from: 'mini', state: 'missing', text: "The Mini isn't answering: no GitHub data from it yet on this machine." } }, now)
    expect(missing.tone).toBe('red')
    expect(missing.text).not.toMatch(/sign-in|reach GitHub/)
  })
  it('a Mac (no source) keeps the old banner exactly', () => {
    expect(prFetchBanner({ errors: [], projects: 2 })).toBeNull()
    expect(prFetchBanner({ errors: [{ repo: 'o/a', message: 'HTTP 401' }, { repo: 'o/b', message: 'HTTP 401' }], projects: 2, lastGoodAt: null }).text).toMatch(/sign-in expired/)
  })
})

describe('readNetworkRegistry', () => {
  it('missing or corrupt registry is {} (and an unknown Linux box then reads as pull-only)', async () => {
    const { readNetworkRegistry } = await import('../electron/main/github_feed.js')
    expect(readNetworkRegistry('/nonexistent.json')).toEqual({})
    expect(readNetworkRegistry(feedFile('{"devices": [oops'))).toEqual({})
    expect(readNetworkRegistry(feedFile({ devices: { a: { accepts: ['test'] } } }))).toEqual({ a: { accepts: ['test'] } })
    expect(isPullOnlyNode({ deviceId: null, registry: readNetworkRegistry('/nonexistent.json'), platform: 'linux', env: {} })).toBe(true)
  })
})

describe('the box never acts on the PRs it shows (marvin#954)', () => {
  it('Approve, Deny and send-back refuse on a pull-only node, in plain words', async () => {
    const { assertActsHere, canMergeHere } = await import('../electron/main/github_feed.js')
    expect(() => assertActsHere(true)).toThrow(/happen on a Mac/)
    try { assertActsHere(true) } catch (e) { expect(e.code).toBe('PULL_ONLY') }
    expect(() => assertActsHere(false)).not.toThrow()
    expect(canMergeHere(true, true)).toBe(false)
    expect(canMergeHere(false, true)).toBe(true)
    expect(canMergeHere(false, false)).toBe(false)
  })
  it('index.js wires the guard into every acting MR handler', async () => {
    const { readFileSync } = await import('fs')
    const src = readFileSync(new URL('../electron/main/index.js', import.meta.url), 'utf-8')
    for (const h of ['mr:deny', 'mr:sendBackForOptions', 'mr:clearSentBack']) {
      const at = src.indexOf(`ipcMain.handle('${h}'`)
      expect(at).toBeGreaterThan(-1)
      expect(src.slice(at, at + 200)).toMatch(/assertActsHere\(\)/)
    }
    expect(src).toMatch(/const assertMergeable = \(url\) => \{\n\s+assertActsHere\(\)/)
    expect((src.match(/canMerge: \(repo\) => canMergeHere\(pullOnly,/g) || []).length).toBe(2)
  })
})
