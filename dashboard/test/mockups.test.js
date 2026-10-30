import { describe, it, expect, vi } from 'vitest'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import {
  detectMockups, cleanPagePath, resolveMockupPath, mockupRequestAllowed, createMockupSource, mimeFor, GONE, MOCKUP_CSP
} from '../electron/main/mockups.js'

// G-Eskayo/marvin#938: a PR's clickable mock-up opens inside MARVIN, read from the PR's head commit.

const FILES_934 = [
  { path: 'dashboard/test/answers_are_approval_proto.test.js' },
  { path: 'docs/design/answers-are-approval-924/README.md' },
  { path: 'docs/design/answers-are-approval-924/answer_state.js' },
  { path: 'docs/design/answers-are-approval-924/index.html' }
]

describe('detectMockups: which PRs carry a mock-up', () => {
  it('a changed docs/design/**/index.html is one (PR #934)', () => {
    expect(detectMockups('Mock-up for #924.', FILES_934)).toEqual([
      { path: 'docs/design/answers-are-approval-924/index.html', dir: 'docs/design/answers-are-approval-924', name: 'answers-are-approval-924' }
    ])
  })
  it('deeper folders count; the folder is the mock-up', () => {
    const [m] = detectMockups('', ['docs/design/seal/v2/index.html'])
    expect(m).toEqual({ path: 'docs/design/seal/v2/index.html', dir: 'docs/design/seal/v2', name: 'v2' })
  })
  it('the marker names a page', () => {
    expect(detectMockups('Look at this\n<!-- marvin:mockup prototypes/board/index.html -->', [])).toEqual([
      { path: 'prototypes/board/index.html', dir: 'prototypes/board', name: 'board' }
    ])
  })
  it('both: the marker wins and the changed design pages are ignored', () => {
    const got = detectMockups('<!-- marvin:mockup prototypes/x/index.html -->', FILES_934)
    expect(got.map((m) => m.path)).toEqual(['prototypes/x/index.html'])
  })
  it('none: an ordinary PR, a README under docs/design, an index.html elsewhere', () => {
    expect(detectMockups('Fixes a bug', [{ path: 'lib/x.py' }])).toEqual([])
    expect(detectMockups('', [{ path: 'docs/design/a/README.md' }, { path: 'dashboard/index.html' }, { path: 'docs/designs/a/index.html' }])).toEqual([])
    expect(detectMockups(undefined, undefined)).toEqual([])
    expect(detectMockups(null, 'not a list')).toEqual([])
  })
  it('two mock-ups: both, in order, once each', () => {
    const files = ['docs/design/a/index.html', 'docs/design/b/index.html', 'docs/design/a/index.html']
    expect(detectMockups('', files).map((m) => m.name)).toEqual(['a', 'b'])
    const marked = detectMockups('<!-- marvin:mockup a/index.html -->\n<!--marvin:mockup b/page.html-->\n<!-- marvin:mockup a/index.html -->', [])
    expect(marked.map((m) => m.path)).toEqual(['a/index.html', 'b/page.html'])
  })
  it('a marker quoted in code is text, not a mock-up (this ticket\'s own body quotes it)', () => {
    expect(detectMockups('the body has `<!-- marvin:mockup path/to/index.html -->`', [])).toEqual([])
    expect(detectMockups('```\n<!-- marvin:mockup x/index.html -->\n```', [])).toEqual([])
  })
  it('a marker that points outside the repo or at a non-page is dropped, and the files are used instead', () => {
    for (const bad of ['../etc/index.html', '/abs/index.html', 'https://evil.example/index.html', 'docs/a.js', 'a/%2e%2e/index.html', 'a\\b/index.html', 'javascript:alert(1)']) {
      expect(detectMockups(`<!-- marvin:mockup ${bad} -->`, FILES_934).map((m) => m.path)).toEqual(['docs/design/answers-are-approval-924/index.html'])
    }
  })
  it('caps a runaway list', () => {
    const files = Array.from({ length: 40 }, (_, i) => `docs/design/m${i}/index.html`)
    expect(detectMockups('', files)).toHaveLength(8)
  })
})

describe('cleanPagePath', () => {
  it('keeps a plain repo path, refuses the rest', () => {
    expect(cleanPagePath('./docs/design/a/index.html')).toBe('docs/design/a/index.html')
    for (const bad of ['', null, 'docs//a.html', 'docs/./a.html', 'C:/x.html', 'file:///x.html', 'a/../b.html', 'a/b.htmlx']) expect(cleanPagePath(bad)).toBeNull()
  })
})

describe('resolveMockupPath: a page may read only its own folder', () => {
  const DIR = 'docs/design/answers-are-approval-924'
  it('serves the page and its relative files', () => {
    expect(resolveMockupPath(DIR, '/index.html')).toBe(`${DIR}/index.html`)
    expect(resolveMockupPath(DIR, '/answer_state.js')).toBe(`${DIR}/answer_state.js`)
    expect(resolveMockupPath(DIR, '/img/a%20b.png')).toBe(`${DIR}/img/a b.png`)
    expect(resolveMockupPath(DIR, '/')).toBe(`${DIR}/index.html`)
    expect(resolveMockupPath(DIR, '')).toBe(`${DIR}/index.html`)
  })
  it('refuses .. in every spelling', () => {
    for (const p of ['/../README.md', '/../../../.git/config', '/a/../../x', '/%2e%2e/x', '/%2E%2E/%2e%2e/x', '/..%2fx', '/%2e%2e%2f%2e%2e%2fsecret', '/%252e%252e/x', '/a/..']) {
      expect(resolveMockupPath(DIR, p), p).toBeNull()
    }
  })
  it('refuses absolute paths, backslashes, NUL bytes and bad encodings', () => {
    for (const p of ['//etc/passwd', '/%2fetc/passwd', '/..\\x', '/a%5c..%5cx', '/a%00.js', '/%E0%A4%A', '/%']) {
      const got = resolveMockupPath(DIR, p)
      // //etc/passwd collapses to the folder's own etc/passwd, which is inside: what matters is it never leaves it.
      if (got !== null) expect(got.startsWith(`${DIR}/`), p).toBe(true)
      else expect(got).toBeNull()
    }
    expect(resolveMockupPath(DIR, '/a%00.js')).toBeNull()
    expect(resolveMockupPath(DIR, '/a%5c..%5cx')).toBeNull()
  })
  it('a sibling folder with the same prefix is outside', () => {
    expect(resolveMockupPath('docs/design/a', '/../a-evil/index.html')).toBeNull()
  })
  it('a page at the repo root still cannot climb', () => {
    expect(resolveMockupPath('', '/x.js')).toBe('x.js')
    expect(resolveMockupPath('', '/../x.js')).toBeNull()
  })
})

describe('mockupRequestAllowed: the network block', () => {
  it('lets only marvin-mockup:// through', () => {
    expect(mockupRequestAllowed('marvin-mockup://abc/index.html')).toBe(true)
    for (const u of ['https://example.com/x.js', 'http://127.0.0.1:8080/', 'ws://localhost/', 'wss://x', 'file:///etc/passwd', 'prmedia://media/x', 'data:text/html,hi', 'blob:https://x/1', 'chrome://gpu', 'devtools://x', 'ftp://x', '', 'not a url', null]) {
      expect(mockupRequestAllowed(u), String(u)).toBe(false)
    }
  })
  it('the page\'s CSP also refuses outside connections', () => {
    expect(MOCKUP_CSP).toContain("connect-src marvin-mockup:")
    expect(MOCKUP_CSP).not.toMatch(/https?:/)
  })
})

describe('mimeFor', () => {
  it('names what a page loads', () => {
    expect(mimeFor('a/index.html')).toMatch(/^text\/html/)
    expect(mimeFor('a/answer_state.js')).toMatch(/^text\/javascript/)
    expect(mimeFor('a/x.css')).toMatch(/^text\/css/)
    expect(mimeFor('a/noext')).toBe('application/octet-stream')
  })
})

// A fake GitHub contents API.
const res = (status, body, json) => ({
  status,
  ok: status >= 200 && status < 300,
  arrayBuffer: async () => Buffer.from(body || ''),
  json: async () => json || {}
})

describe('createMockupSource: GitHub, signed in (no clone on this Mac)', () => {
  const target = { repo: 'G-Eskayo/marvin-instance', sha: 'a990349dbd151f99eb4e17b84b150935aa673bb3', number: 6 }
  it('a private repo loads through the contents API at the head commit, with the token', async () => {
    const fetchFn = vi.fn(async () => res(200, '<html>hi</html>'))
    const src = createMockupSource({ fetchFn, token: () => 'tok123', resolveClone: async () => null, exec: vi.fn() })
    const r = await src.read(target, 'docs/design/x/index.html')
    expect(r.ok).toBe(true)
    expect(r.body.toString()).toBe('<html>hi</html>')
    expect(r.mime).toMatch(/text\/html/)
    expect(r.source).toBe('github')
    const [url, opts] = fetchFn.mock.calls[0]
    expect(url).toBe(`https://api.github.com/repos/G-Eskayo/marvin-instance/contents/docs/design/x/index.html?ref=${target.sha}`)
    expect(opts.headers.Authorization).toBe('Bearer tok123')
    expect(opts.headers.Accept).toBe('application/vnd.github.raw')
  })
  it('a deleted branch (GitHub no longer has the commit) says the mock-up is gone', async () => {
    const fetchFn = vi.fn(async () => res(404, '', { message: 'No commit found for the ref a990349' }))
    const r = await createMockupSource({ fetchFn, token: () => 't' }).read(target, 'docs/design/x/index.html')
    expect(r).toEqual({ ok: false, gone: 'branch', reason: GONE.branch })
    expect(r.reason).toBe('This mock-up is gone: its branch was deleted')
  })
  it('a missing file says the page is gone, not that the branch is', async () => {
    const fetchFn = vi.fn(async () => res(404, '', { message: 'Not Found' }))
    const r = await createMockupSource({ fetchFn, token: () => 't' }).read(target, 'docs/design/x/index.html')
    expect(r.gone).toBe('file')
    expect(r.reason).toMatch(/gone/)
  })
  it('a 404 with no token is a sign-in problem (private repos 404 to strangers)', async () => {
    const r = await createMockupSource({ fetchFn: async () => res(404, '', { message: 'Not Found' }), token: () => '' }).read(target, 'a/index.html')
    expect(r.gone).toBe('access')
  })
  it('403, a network failure and a 500 are plain messages, never a throw', async () => {
    expect((await createMockupSource({ fetchFn: async () => res(403), token: () => 't' }).read(target, 'a/index.html')).gone).toBe('access')
    expect((await createMockupSource({ fetchFn: async () => { throw new Error('ENOTFOUND') }, token: () => 't' }).read(target, 'a/index.html')).gone).toBe('network')
    expect((await createMockupSource({ fetchFn: async () => res(500), token: () => 't' }).read(target, 'a/index.html')).reason).toMatch(/500/)
  })
  it('no commit and no branch name: gone, without asking GitHub', async () => {
    const fetchFn = vi.fn()
    expect((await createMockupSource({ fetchFn }).read({ repo: 'o/r' }, 'a/index.html')).gone).toBe('branch')
    expect(fetchFn).not.toHaveBeenCalled()
  })
  it('a malformed repo or ref is refused before any request', async () => {
    const fetchFn = vi.fn()
    expect((await createMockupSource({ fetchFn }).read({ repo: '../x', sha: 'abcdef1' }, 'a/index.html')).ok).toBe(false)
    expect((await createMockupSource({ fetchFn }).read({ repo: 'o/r', ref: 'a b;rm' }, 'a/index.html')).gone).toBe('branch')
    expect(fetchFn).not.toHaveBeenCalled()
  })
  it('falls back to the branch name when the head commit is unknown', async () => {
    const fetchFn = vi.fn(async () => res(200, 'x'))
    await createMockupSource({ fetchFn, token: () => 't' }).read({ repo: 'o/r', ref: 'design/924-x' }, 'a/index.html')
    expect(fetchFn.mock.calls[0][0]).toContain('?ref=design%2F924-x')
  })
})

// A real git repository stands in for the local clone (real collaborator, not a mock).
const execP = promisify(execFile)
async function makeRepo() {
  const dir = mkdtempSync(path.join(tmpdir(), 'mockup-src-'))
  const git = (...a) => execP('git', ['-C', dir, ...a])
  await git('init', '-q')
  await git('config', 'user.email', 't@t')
  await git('config', 'user.name', 't')
  mkdirSync(path.join(dir, 'docs/design/m'), { recursive: true })
  writeFileSync(path.join(dir, 'docs/design/m/index.html'), '<script src="answer_state.js"></script>')
  writeFileSync(path.join(dir, 'docs/design/m/answer_state.js'), 'window.x = 1')
  await git('add', '.')
  await git('commit', '-qm', 'mock')
  const sha = (await git('rev-parse', 'HEAD')).stdout.trim()
  return { dir, sha, cleanup: () => rmSync(dir, { recursive: true, force: true }) }
}

describe('createMockupSource: the local clone first', () => {
  it('reads the file at the commit with git show, and never asks GitHub', async () => {
    const repo = await makeRepo()
    try {
      const fetchFn = vi.fn()
      const src = createMockupSource({ exec: execP, resolveClone: async () => repo.dir, fetchFn })
      const r = await src.read({ repo: 'o/r', sha: repo.sha }, 'docs/design/m/answer_state.js')
      expect(r.ok).toBe(true)
      expect(r.source).toBe('local')
      expect(r.body.toString()).toBe('window.x = 1')
      expect(fetchFn).not.toHaveBeenCalled()
    } finally { repo.cleanup() }
  })
  it('a file missing at that commit is "gone", from the clone', async () => {
    const repo = await makeRepo()
    try {
      const r = await createMockupSource({ exec: execP, resolveClone: async () => repo.dir, fetchFn: vi.fn() }).read({ repo: 'o/r', sha: repo.sha }, 'docs/design/m/nope.js')
      expect(r).toEqual({ ok: false, gone: 'file', reason: GONE.file })
    } finally { repo.cleanup() }
  })
  it('a clone without the commit (and no remote to fetch it) falls through to GitHub', async () => {
    const repo = await makeRepo()
    try {
      const fetchFn = vi.fn(async () => res(200, 'remote'))
      const r = await createMockupSource({ exec: execP, resolveClone: async () => repo.dir, fetchFn, token: () => 't' }).read({ repo: 'o/r', sha: 'f'.repeat(40), number: 9 }, 'docs/design/m/index.html')
      expect(r.source).toBe('github')
      expect(r.body.toString()).toBe('remote')
    } finally { repo.cleanup() }
  })
  it('asks git to fetch the PR head ref when the clone lacks the commit', async () => {
    const calls = []
    const exec = vi.fn(async (_cmd, args) => {
      calls.push(args.slice(2).join(' '))
      if (args[2] === 'cat-file') throw new Error('missing')
      if (args[2] === 'fetch') throw new Error('offline')
      return { stdout: Buffer.from('') }
    })
    const fetchFn = vi.fn(async () => res(200, 'x'))
    await createMockupSource({ exec, resolveClone: async () => '/clone', fetchFn }).read({ repo: 'o/r', sha: 'a'.repeat(40), number: 934 }, 'a/index.html')
    expect(calls).toContain('fetch --quiet --no-tags origin refs/pull/934/head')
    expect(fetchFn).toHaveBeenCalled()
  })
  it('looks for the clone once per repo, however many files the page loads', async () => {
    const repo = await makeRepo()
    try {
      const resolveClone = vi.fn(async () => repo.dir)
      const src = createMockupSource({ exec: execP, resolveClone })
      await Promise.all([src.read({ repo: 'o/r', sha: repo.sha }, 'docs/design/m/index.html'), src.read({ repo: 'o/r', sha: repo.sha }, 'docs/design/m/answer_state.js')])
      expect(resolveClone).toHaveBeenCalledTimes(1)
    } finally { repo.cleanup() }
  })
})
