import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync, readFileSync, readdirSync, existsSync, mkdirSync, chmodSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createSavedDocs, gitBlobSha, docTreeFromPaths, savedFileFor } from '../electron/main/docs_saved.js'

// #565 "Docs tab: stop calling GitHub on every click for projects without a local clone". Every GitHub call goes
// through a counting fake: `probe` is the one conditional (ETag) request, `exec` is any `gh` call.

const REPO = 'G-Eskayo/paper-dive'
const files = {
  'CONTEXT.md': '# Context\n',
  'README.md': '# paper-dive\n',
  'docs/adr/0001-first.md': '# 1. First\n',
  'src/main.py': 'print(1)\n'
}

function fakeGithub(initial = files) {
  let state = { ...initial }
  let version = 1
  const calls = { probe: 0, exec: 0, fetched: [] }
  const etag = () => `W/"v${version}"`
  const probe = async (repo, known) => {
    calls.probe++
    if (github.down) throw new Error('getaddrinfo ENOTFOUND api.github.com')
    if (github.status) return { status: github.status }
    if (known === etag()) return { status: 304, etag: etag() }
    return {
      status: 200,
      etag: etag(),
      body: { tree: Object.entries(state).map(([p, text]) => ({ path: p, type: 'blob', sha: gitBlobSha(text) })) }
    }
  }
  const exec = async (cmd, args) => {
    calls.exec++
    expect(cmd).toBe('gh')
    const url = args.find((a) => a.startsWith('repos/'))
    const p = decodeURIComponent(url.split('/contents/')[1])
    calls.fetched.push(p)
    if (github.failFile === p) throw new Error('HTTP 502')
    if (!(p in state)) throw new Error('HTTP 404')
    const raw = args.includes('Accept: application/vnd.github.raw')
    return { stdout: raw ? state[p] : Buffer.from(state[p]).toString('base64') + '\n' }
  }
  const github = {
    probe,
    exec,
    calls,
    push(change) {
      state = { ...state, ...change }
      for (const [k, v] of Object.entries(change)) if (v === null) delete state[k]
      version++
    },
    down: false,
    status: null,
    failFile: null
  }
  return github
}

let dir
let clock
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'docs-saved-'))
  clock = 1_000_000
})
afterEach(() => rmSync(dir, { recursive: true, force: true }))

const store = (gh, extra = {}) => createSavedDocs({ dir, probe: gh.probe, exec: gh.exec, now: () => clock, ...extra })
const paths = (tree) => tree.flatMap((e) => (e.section ? e.items : [e])).map((e) => e.path)

describe('gitBlobSha', () => {
  it('matches git hash-object for text, including multi-byte characters', () => {
    // `printf 'hello\n' | git hash-object --stdin`
    expect(gitBlobSha('hello\n')).toBe('ce013625030ba8dba906f756967f9e9ca394464a')
    // `printf 'é\n' | git hash-object --stdin` (2-byte UTF-8: the header counts bytes, not characters)
    expect(gitBlobSha('é\n')).toBe('c6003325155f475bd7c87731607525dce73be9cf')
  })
})

describe('docTreeFromPaths', () => {
  it('lists CONTEXT, README, docs/ sections and root notebooks, and nothing else', () => {
    const t = docTreeFromPaths(['src/x.md', 'README.md', 'CONTEXT.md', 'docs/adr/0001-a.md', 'docs/guide.md', 'a.ipynb', 'deep/b.ipynb'])
    expect(paths(t)).toEqual(['CONTEXT.md', 'README.md', 'docs/adr/0001-a.md', 'docs/guide.md', 'a.ipynb'])
  })
  it('leaves out CONTEXT.md when the repo has none', () => {
    expect(paths(docTreeFromPaths(['README.md']))).toEqual(['README.md'])
  })
})

describe('first fill and clicks', () => {
  it('opening a project 10 times and a file 10 times costs 0 calls after the first fill', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    const first = await s.revalidate(REPO)
    expect(first.status).toBe('changed')
    const afterFill = { probe: gh.calls.probe, exec: gh.calls.exec }
    expect(afterFill.probe).toBe(1)
    expect(gh.calls.fetched.sort()).toEqual(['CONTEXT.md', 'README.md', 'docs/adr/0001-first.md']) // never src/
    for (let i = 0; i < 10; i++) {
      expect(paths(s.peek(REPO).tree)).toEqual(['CONTEXT.md', 'README.md', 'docs/adr/0001-first.md'])
      expect(await s.content(REPO, 'docs/adr/0001-first.md')).toBe('# 1. First\n')
    }
    expect(gh.calls).toMatchObject(afterFill)
  })

  it('a new store (an app restart) serves the saved copy from disk with no calls', async () => {
    const gh = fakeGithub()
    await store(gh).revalidate(REPO)
    const before = gh.calls.probe + gh.calls.exec
    const again = store(gh)
    expect(again.peek(REPO).tree.length).toBe(3)
    expect(await again.content(REPO, 'README.md')).toBe('# paper-dive\n')
    expect(gh.calls.probe + gh.calls.exec).toBe(before)
  })

  it('peek never touches the network, even with no copy at all', () => {
    const gh = fakeGithub()
    expect(store(gh).peek(REPO)).toBeNull()
    expect(gh.calls.probe + gh.calls.exec).toBe(0)
  })

  it('a file never seen before is fetched once, then saved', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    expect(await s.content(REPO, 'README.md')).toBe('# paper-dive\n')
    expect(await s.content(REPO, 'README.md')).toBe('# paper-dive\n')
    expect(store(gh).peek(REPO).files['README.md']).toBe('# paper-dive\n')
    expect(gh.calls.exec).toBe(1)
  })

  it('a notebook is fetched raw (not base64) and saved as the raw JSON', async () => {
    const gh = fakeGithub({ ...files, 'a.ipynb': '{"cells":[]}' })
    const s = store(gh)
    await s.revalidate(REPO)
    expect(await s.content(REPO, 'a.ipynb')).toBe('{"cells":[]}')
  })
})

describe('revalidation: one conditional request per open', () => {
  it('unchanged: a 304, no downloads, and the copy is marked checked now', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    await s.revalidate(REPO)
    const exec = gh.calls.exec
    clock += 7_200_000
    const r = await s.revalidate(REPO)
    expect(r.status).toBe('unchanged')
    expect(gh.calls.probe).toBe(2)
    expect(gh.calls.exec).toBe(exec)
    expect(s.peek(REPO).checkedAt).toBe(clock)
  })

  it('a HEAD change triggers exactly one refresh, downloading only the docs that changed', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    await s.revalidate(REPO)
    gh.calls.fetched = []
    gh.push({ 'README.md': '# paper-dive v2\n', 'docs/adr/0002-second.md': '# 2\n', 'src/main.py': 'print(2)\n' })
    const r = await s.revalidate(REPO)
    expect(r.status).toBe('changed')
    expect(r.changed.sort()).toEqual(['README.md', 'docs/adr/0002-second.md'])
    expect(gh.calls.fetched.sort()).toEqual(['README.md', 'docs/adr/0002-second.md'])
    expect(await s.content(REPO, 'README.md')).toBe('# paper-dive v2\n')
    expect(paths(r.tree)).toContain('docs/adr/0002-second.md')
    // and the next open is a free 304 again
    expect((await s.revalidate(REPO)).status).toBe('unchanged')
    expect(gh.calls.fetched.length).toBe(2)
  })

  it('a code-only push changes the ETag but downloads nothing and reports unchanged docs', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    await s.revalidate(REPO)
    const exec = gh.calls.exec
    gh.push({ 'src/main.py': 'print(3)\n' })
    expect((await s.revalidate(REPO)).status).toBe('unchanged')
    expect(gh.calls.exec).toBe(exec)
  })

  it('a deleted doc leaves the tree and the saved copy', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    await s.revalidate(REPO)
    gh.push({ 'docs/adr/0001-first.md': null })
    const r = await s.revalidate(REPO)
    expect(r.status).toBe('changed')
    expect(paths(r.tree)).toEqual(['CONTEXT.md', 'README.md'])
    expect(s.peek(REPO).files['docs/adr/0001-first.md']).toBeUndefined()
  })

  it('opens racing each other share one request', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    await Promise.all([s.revalidate(REPO), s.revalidate(REPO), s.revalidate(REPO)])
    expect(gh.calls.probe).toBe(1)
  })

  it('a click while the first fill runs waits for it instead of fetching the file a second time', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    const fill = s.revalidate(REPO)
    const text = await s.content(REPO, 'README.md')
    await fill
    expect(text).toBe('# paper-dive\n')
    expect(gh.calls.fetched.filter((p) => p === 'README.md').length).toBe(1)
  })

  it('a click on a saved doc answers at once while the open-time check is still waiting on GitHub', async () => {
    const gh = fakeGithub()
    await store(gh).revalidate(REPO)
    let release
    const slow = createSavedDocs({ dir, exec: gh.exec, now: () => clock, probe: () => new Promise((r) => (release = () => r({ status: 304, etag: 'W/"v1"' }))) })
    const check = slow.revalidate(REPO)
    const t0 = Date.now()
    expect(await slow.content(REPO, 'README.md')).toBe('# paper-dive\n')
    expect(Date.now() - t0).toBeLessThan(50)
    release()
    expect((await check).status).toBe('unchanged')
  })

  it('a doc that fails to download keeps the old ETag, so the next open retries it', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    await s.revalidate(REPO)
    gh.push({ 'README.md': '# v2\n' })
    gh.failFile = 'README.md'
    expect((await s.revalidate(REPO)).status).toBe('offline')
    expect(await s.content(REPO, 'README.md')).toBe('# paper-dive\n') // old text kept, not blanked
    gh.failFile = null
    expect((await s.revalidate(REPO)).status).toBe('changed')
    expect(await s.content(REPO, 'README.md')).toBe('# v2\n')
  })

  it('does not ask GitHub while the gate is cooling down', async () => {
    const gh = fakeGithub()
    const s = store(gh, { skip: () => true })
    expect((await s.revalidate(REPO)).status).toBe('skipped')
    expect(gh.calls.probe).toBe(0)
  })
})

describe('offline and broken answers', () => {
  it('offline: the saved copy still renders, with its age', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    await s.revalidate(REPO)
    const savedAt = clock
    clock += 2 * 3600_000
    gh.down = true
    const r = await s.revalidate(REPO)
    expect(r.status).toBe('offline')
    expect(r.error).toMatch(/ENOTFOUND/)
    const copy = s.peek(REPO)
    expect(copy.checkedAt).toBe(savedAt) // not claimed as checked
    expect(paths(copy.tree).length).toBe(3)
    expect(await s.content(REPO, 'CONTEXT.md')).toBe('# Context\n')
  })

  it('a 403 or 500 is treated as offline, never as an empty repo', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    await s.revalidate(REPO)
    gh.status = 403
    expect((await s.revalidate(REPO)).status).toBe('offline')
    expect(paths(s.peek(REPO).tree).length).toBe(3)
  })

  it('a 200 with a malformed body keeps the copy', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    await s.revalidate(REPO)
    const bad = createSavedDocs({ dir, exec: gh.exec, now: () => clock, probe: async () => ({ status: 200, etag: 'x', body: { tree: 'nope' } }) })
    expect((await bad.revalidate(REPO)).status).toBe('offline')
    expect(paths(bad.peek(REPO).tree).length).toBe(3)
  })

  it('a corrupt cache file rebuilds once instead of looping', async () => {
    const gh = fakeGithub()
    mkdirSync(dir, { recursive: true })
    writeFileSync(savedFileFor(dir, REPO), '{not json')
    const s = store(gh)
    expect(s.peek(REPO)).toBeNull()
    await s.revalidate(REPO)
    expect(gh.calls.probe).toBe(1)
    expect(JSON.parse(readFileSync(savedFileFor(dir, REPO), 'utf8')).tree.length).toBe(3)
    const calls = gh.calls.probe + gh.calls.exec
    for (let i = 0; i < 5; i++) store(gh).peek(REPO)
    expect(gh.calls.probe + gh.calls.exec).toBe(calls)
  })

  it('a cache file of the wrong shape is ignored, not trusted', () => {
    const gh = fakeGithub()
    writeFileSync(savedFileFor(dir, REPO), JSON.stringify({ tree: 'x', files: [] }))
    expect(store(gh).peek(REPO)).toBeNull()
  })

  it('an unwritable cache folder still serves from memory without re-fetching', async () => {
    const gh = fakeGithub()
    const ro = path.join(dir, 'ro')
    mkdirSync(ro)
    chmodSync(ro, 0o500)
    try {
      const s = createSavedDocs({ dir: ro, probe: gh.probe, exec: gh.exec, now: () => clock })
      await s.revalidate(REPO)
      const n = gh.calls.exec
      expect(await s.content(REPO, 'README.md')).toBe('# paper-dive\n')
      expect(gh.calls.exec).toBe(n)
    } finally {
      chmodSync(ro, 0o700)
    }
  })

  it('hostile repo names and paths never escape the cache folder or reach gh unchecked', async () => {
    const gh = fakeGithub()
    const s = store(gh)
    expect(savedFileFor(dir, '../../etc/passwd').startsWith(dir + path.sep)).toBe(true)
    expect(path.dirname(savedFileFor(dir, 'G-Eskayo/../../x'))).toBe(dir)
    await expect(s.content(REPO, '../../secrets')).rejects.toThrow(/not a doc path/i)
    await expect(s.content(REPO, '/etc/passwd')).rejects.toThrow(/not a doc path/i)
    expect(gh.calls.exec).toBe(0)
    expect(readdirSync(dir).every((n) => n.endsWith('.json'))).toBe(true)
  })
})

describe('seeding from the docs search index (what we already fetched)', () => {
  it('serves the index text at once, then the first check downloads only what differs', async () => {
    const gh = fakeGithub()
    const seed = () => ({
      at: '2026-10-21T10:00:00Z',
      docs: [
        { path: 'CONTEXT.md', label: 'CONTEXT.md', content: '# Context\n' },
        { path: 'README.md', label: 'README.md', content: '# stale readme\n' },
        { path: 'docs/adr/0001-first.md', label: '0001-first.md', content: '# 1. First\n' }
      ]
    })
    const s = store(gh, { seed })
    const copy = s.peek(REPO)
    expect(paths(copy.tree)).toEqual(['CONTEXT.md', 'README.md', 'docs/adr/0001-first.md'])
    expect(copy.savedAt).toBe(Date.parse('2026-10-21T10:00:00Z'))
    expect(gh.calls.probe + gh.calls.exec).toBe(0)
    const r = await s.revalidate(REPO)
    expect(gh.calls.fetched).toEqual(['README.md']) // the two that match by blob sha are kept
    expect(r.changed).toEqual(['README.md'])
  })

  it('never seeds a notebook from the index (it holds the markdown view, not the raw JSON)', () => {
    const gh = fakeGithub()
    const s = store(gh, { seed: () => ({ at: null, docs: [{ path: 'a.ipynb', label: 'a.ipynb', content: '# md view' }] }) })
    expect(s.peek(REPO)?.files?.['a.ipynb']).toBeUndefined()
  })

  it('a throwing seed is the same as no seed', () => {
    const gh = fakeGithub()
    expect(store(gh, { seed: () => { throw new Error('boom') } }).peek(REPO)).toBeNull()
  })
})

it('writes nothing outside its own folder (temp HOME only)', async () => {
  const gh = fakeGithub()
  await store(gh).revalidate(REPO)
  expect(existsSync(savedFileFor(dir, REPO))).toBe(true)
})

describe('createTreeProbe (gh_watch.js pattern)', () => {
  const resp = (status, body, etag) => ({ status, headers: { get: (h) => (h.toLowerCase() === 'etag' ? etag : null) }, json: async () => body })
  it('sends If-None-Match with the saved ETag and the shared token, and reads no body on a 304', async () => {
    const { createTreeProbe, treeEndpoint } = await import('../webhook-server/gh_watch.js')
    let jsonRead = false
    const doFetch = async (url, opts) => {
      expect(url).toBe(treeEndpoint('G-Eskayo/paper-dive'))
      expect(opts.headers).toMatchObject({ 'If-None-Match': 'W/"e1"', Authorization: 'Bearer t' })
      return { ...resp(304, null, 'W/"e1"'), json: async () => ((jsonRead = true), null) }
    }
    expect(await createTreeProbe({ GH_TOKEN: 't' }, doFetch)('G-Eskayo/paper-dive', 'W/"e1"')).toEqual({ status: 304, etag: 'W/"e1"' })
    expect(jsonRead).toBe(false)
  })
  it('returns the tree body on a 200, and sends no If-None-Match without a saved ETag', async () => {
    const { createTreeProbe } = await import('../webhook-server/gh_watch.js')
    const doFetch = async (_url, opts) => {
      expect(opts.headers['If-None-Match']).toBeUndefined()
      return resp(200, { tree: [] }, 'W/"e2"')
    }
    expect(await createTreeProbe({}, doFetch)('o/r')).toEqual({ status: 200, etag: 'W/"e2"', body: { tree: [] } })
  })
})
