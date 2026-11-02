import { describe, it, expect } from 'vitest'
import { mkdtempSync, readFileSync, statSync, writeFileSync, readdirSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { createGithubFeedWriter, atomicWrite } from '../webhook-server/github_feed_writer.js'
import { createFeedSource } from '../electron/main/github_feed.js'
import { createChangeDetector, startChangeWatch } from '../webhook-server/gh_watch.js'

const REPO = 'G-Eskayo/marvin'
const pr = (n, extra = {}) => ({ number: n, title: `PR ${n}`, url: `https://github.com/${REPO}/pull/${n}`, isDraft: false, body: 'b', files: [], baseRefName: 'main', headRefName: `h${n}`, headRefOid: `sha${n}`, mergeable: 'MERGEABLE', statusCheckRollup: [], ...extra })

function fakeGh({ prs = [pr(1)], issues = [{ number: 9, labels: [] }], fail = null } = {}) {
  const calls = []
  const gh = async (args) => {
    calls.push(args.join(' '))
    if (fail && fail(args)) throw new Error('gh: HTTP 502 from GitHub')
    if (args[0] === 'pr' && args[1] === 'list') return JSON.stringify(prs)
    if (args[0] === 'issue' && args[1] === 'list') return JSON.stringify(args.includes('closed') ? [] : issues)
    throw new Error(`unexpected gh ${args.join(' ')}`)
  }
  return { gh, calls }
}

function setup(opts = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'gh-feed-w-'))
  const path = join(dir, 'github-feed.json')
  let t = 1_800_000_000_000
  const g = fakeGh(opts)
  const logs = []
  const w = createGithubFeedWriter({ path, repos: () => opts.repos || [REPO], gh: g.gh, host: 'mac-mini-1', now: () => t, log: (m) => logs.push(m) })
  return { dir, path, w, g, logs, tick: (ms) => { t += ms }, now: () => t }
}

describe('github feed writer (the Mini side of marvin#954)', () => {
  it('one refresh writes what the box MR list and board read, and the box reads it back unchanged', async () => {
    const s = setup()
    await s.w.refresh(REPO)
    const src = createFeedSource({ path: s.path, now: s.now })
    expect(src.openPrs(REPO)).toEqual([pr(1)])
    expect(src.board(REPO).issues).toEqual([{ number: 9, labels: [] }])
    expect(src.board(REPO).prs).toEqual([{ number: 1, title: 'PR 1', url: `https://github.com/${REPO}/pull/1`, isDraft: false, body: 'b', files: [], state: 'OPEN' }])
    // the board's PR list came from the full list: one pr list call, not two
    expect(s.g.calls.filter((c) => c.startsWith('pr list'))).toHaveLength(1)
  })

  it('the file is private (600) and holds only gh output: no token, even one in the environment', async () => {
    process.env.GH_TOKEN_TEST_CANARY = 'ghp_canary_should_never_appear'
    const s = setup()
    await s.w.refresh(REPO)
    expect(statSync(s.path).mode & 0o777).toBe(0o600)
    expect(readFileSync(s.path, 'utf-8')).not.toMatch(/ghp_|github_pat_|canary/)
    delete process.env.GH_TOKEN_TEST_CANARY
  })

  it('GitHub down: the last good entry is kept, alive_at stops, and it says why once in its log', async () => {
    const s = setup()
    await s.w.refresh(REPO)
    const before = JSON.parse(readFileSync(s.path, 'utf-8'))
    s.tick(5 * 60_000)
    s.g.calls.length = 0
    const s2 = { ...s }
    const failing = createGithubFeedWriter({ path: s.path, repos: () => [REPO], gh: fakeGh({ fail: () => true }).gh, now: s2.now, log: (m) => s.logs.push(m) })
    await failing.refresh(REPO)
    const after = JSON.parse(readFileSync(s.path, 'utf-8'))
    expect(after.repos[REPO]).toEqual(before.repos[REPO])
    expect(after.alive_at).toBe(before.alive_at)
    expect(s.logs.at(-1)).toMatch(/could not read G-Eskayo\/marvin: gh: HTTP 502/)
  })

  it('a burst of change pings costs one running read plus one queued, not one each', async () => {
    const s = setup()
    await Promise.all([s.w.refresh(REPO), s.w.refresh(REPO), s.w.refresh(REPO), s.w.refresh(REPO)])
    expect(s.g.calls.filter((c) => c.startsWith('pr list'))).toHaveLength(2)
  })

  it('a check change re-reads only the PR list; a queued full read still reads the board', async () => {
    const s = setup()
    await s.w.refresh(REPO, { prsOnly: true })
    expect(s.g.calls.every((c) => c.startsWith('pr list'))).toBe(true)
    s.g.calls.length = 0
    await Promise.all([s.w.refresh(REPO, { prsOnly: true }), s.w.refresh(REPO)])
    expect(s.g.calls.some((c) => c.startsWith('issue list'))).toBe(true)
  })

  it('a repo outside the registry is never read, and a repo dropped from it leaves the feed', async () => {
    let repos = [REPO, 'G-Eskayo/other']
    const dir = mkdtempSync(join(tmpdir(), 'gh-feed-w-'))
    const path = join(dir, 'f.json')
    const g = fakeGh()
    const w = createGithubFeedWriter({ path, repos: () => repos, gh: g.gh, log: () => {} })
    expect(await w.refresh('evil/repo')).toBe(false)
    expect(g.calls).toHaveLength(0)
    await w.refreshAll()
    expect(Object.keys(JSON.parse(readFileSync(path, 'utf-8')).repos).sort()).toEqual(['G-Eskayo/marvin', 'G-Eskayo/other'])
    repos = [REPO]
    await w.refresh(REPO)
    expect(Object.keys(JSON.parse(readFileSync(path, 'utf-8')).repos)).toEqual([REPO])
  })

  it('alive: written at most once a minute, and never for a round where GitHub answered nothing', async () => {
    const s = setup()
    expect(s.w.alive(0)).toBe(false)
    expect(s.w.alive(1)).toBe(true)
    s.tick(30_000)
    expect(s.w.alive(1)).toBe(false)
    s.tick(31_000)
    expect(s.w.alive(1)).toBe(true)
    expect(JSON.parse(readFileSync(s.path, 'utf-8')).alive_at).toBe(s.now())
  })

  it('starts from a corrupt previous feed without crashing, and replaces it', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'gh-feed-w-'))
    const path = join(dir, 'f.json')
    writeFileSync(path, '{"repos": [trunc')
    const w = createGithubFeedWriter({ path, repos: () => [REPO], gh: fakeGh().gh, log: () => {} })
    await w.refresh(REPO)
    expect(JSON.parse(readFileSync(path, 'utf-8')).repos[REPO].prs.value).toHaveLength(1)
  })

  it('pendingHeads: only the feed PRs whose checks are still running', async () => {
    const s = setup({ prs: [pr(1, { statusCheckRollup: [{ __typename: 'CheckRun', name: 'ci', status: 'IN_PROGRESS', conclusion: null }] }), pr(2)] })
    await s.w.refresh(REPO)
    expect(s.w.pendingHeads().map((h) => h.sha)).toEqual(['sha1'])
  })

  it('atomicWrite leaves no temp file behind', () => {
    const dir = mkdtempSync(join(tmpdir(), 'gh-feed-w-'))
    atomicWrite(join(dir, 'a.json'), '{}')
    expect(readdirSync(dir)).toEqual(['a.json'])
  })
})

describe('change watch: how many repos GitHub answered, for alive_at', () => {
  it('counts 200s and 304s, not errors or throws', async () => {
    const codes = { 'o/a': 304, 'o/b': 500 }
    const d = createChangeDetector({ probe: async (repo) => { if (repo === 'o/c') throw new Error('offline'); return { status: codes[repo] } }, onChange: () => {} })
    expect(await d.tick(['o/a', 'o/b', 'o/c'])).toBe(1)
  })
  it('onTick gets the count, and a throwing onTick does not stop the watch', async () => {
    const seen = []
    let run
    startChangeWatch({ getRepos: () => ['o/a'], probe: async () => ({ status: 304 }), ping: () => {}, setIntervalFn: (fn) => { run = fn }, onTick: (n) => { seen.push(n); throw new Error('listener broke') } })
    await new Promise((r) => setTimeout(r, 0))
    await run()
    expect(seen).toEqual([1, 1])
  })
})
