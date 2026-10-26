import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createDocsService, MASTER_ID } from '../electron/main/docs_service.js'
import { createSavedDocs, gitBlobSha } from '../electron/main/docs_saved.js'

const rec = (over) => ({
  id: 'p1',
  name: 'Project One',
  kind: 'repo',
  repo: 'G-Eskayo/P_One',
  status: 'active',
  localPaths: [],
  docs: { context: false, readme: false, adrCount: 0 },
  tags: [],
  summary_md: '# Project One\n\ncard body\n',
  ...over
})
const catalog = (...projects) => ({ generated_at: '2026-10-05T00:00:00Z', projects })
const withDir = async (fn) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'docsvc-'))
  try {
    return await fn(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}
const svc = (cat, extra = {}) =>
  createDocsService({ getCatalog: () => cat, exec: vi.fn(async () => { throw new Error('404') }), readMaster: () => '# Where things are\n', fallbackRepos: () => [], ...extra })

describe('repos', () => {
  it('lists the master doc first, then every catalog project with id, name and status', async () => {
    const out = await svc(catalog(rec(), rec({ id: 'p2', name: 'Two', status: 'dormant', kind: 'local', repo: null }))).repos()
    expect(out.repos.map((r) => r.id)).toEqual([MASTER_ID, 'p1', 'p2'])
    expect(out.repos[1]).toMatchObject({ name: 'Project One', status: 'active' })
  })

  it('marks projects that have a readable local folder', async () =>
    withDir(async (dir) => {
      const out = await svc(catalog(rec({ localPaths: [dir] }))).repos()
      expect(out.repos.find((r) => r.id === 'p1').local).toBe(dir)
    }))

  it('falls back to the old doc-first repo list when no catalog exists yet', async () => {
    const out = await svc(null, { fallbackRepos: () => [{ name: 'marvin' }] }).repos()
    expect(out.repos.map((r) => r.id)).toEqual([MASTER_ID, 'marvin'])
  })
})

describe('tree', () => {
  it('always offers the project card first', async () => {
    const t = await svc(catalog(rec({ kind: 'local', repo: null }))).tree('p1')
    expect(t.tree).toEqual([{ path: 'PROJECT.md', label: 'Project card' }])
    expect(t.source).toBe('card')
  })

  it('adds only the docs that exist in a local folder', async () =>
    withDir(async (dir) => {
      writeFileSync(path.join(dir, 'README.md'), 'hi')
      const t = await svc(catalog(rec({ localPaths: [dir] }))).tree('p1')
      expect(t.source).toBe('local')
      expect(t.tree.map((e) => e.path)).toEqual(['PROJECT.md', 'README.md'])
    }))

  it('a GitHub-only project with just a README needs no GitHub listing calls', async () => {
    const exec = vi.fn()
    const t = await svc(catalog(rec({ docs: { context: false, readme: true, adrCount: 0 } })), { exec }).tree('p1')
    expect(t.tree.map((e) => e.path)).toEqual(['PROJECT.md', 'README.md'])
    expect(t.source).toBe('github')
    expect(exec).not.toHaveBeenCalled()
  })

  it('the master entry has exactly one page', async () => {
    const t = await svc(catalog(rec())).tree(MASTER_ID)
    expect(t.tree).toEqual([{ path: 'WHERE-THINGS-ARE.md', label: 'Where things are' }])
  })
})

describe('content', () => {
  it('serves the card and the master from memory, local docs from disk, GitHub docs by repo name', async () =>
    withDir(async (dir) => {
      writeFileSync(path.join(dir, 'CONTEXT.md'), '# local ctx\n')
      const s = svc(catalog(rec({ localPaths: [dir] })))
      expect(await s.content('p1', 'PROJECT.md')).toContain('card body')
      expect(await s.content(MASTER_ID, 'WHERE-THINGS-ARE.md')).toContain('Where things are')
      expect(await s.content('p1', 'CONTEXT.md')).toBe('# local ctx\n')
      const exec = vi.fn(async () => ({ stdout: Buffer.from('from github').toString('base64') }))
      const g = svc(catalog(rec({ docs: { context: true, readme: false, adrCount: 0 } })), { exec })
      expect(await g.content('p1', 'CONTEXT.md')).toBe('from github')
      expect(exec.mock.calls[0][1].join(' ')).toContain('repos/G-Eskayo/P_One/contents/CONTEXT.md')
    }))

  it('rejects an unknown project', async () => {
    await expect(svc(catalog(rec())).content('nope', 'CONTEXT.md')).rejects.toThrow(/unknown project/i)
  })
})

describe('localDocs and index sources', () => {
  it('returns a card for every project, the master, and local docs keyed by project id', async () =>
    withDir(async (dir) => {
      mkdirSync(path.join(dir, 'docs', 'adr'), { recursive: true })
      writeFileSync(path.join(dir, 'CONTEXT.md'), '# ctx\n')
      const s = svc(catalog(rec({ localPaths: [dir] }), rec({ id: 'p2', name: 'Two', kind: 'local', repo: null })))
      const { repos, docs } = await s.localDocs()
      expect([...repos]).toEqual(['p1'])
      expect(docs.map((d) => `${d.repo}:${d.path}`).sort()).toEqual(
        [`${MASTER_ID}:WHERE-THINGS-ARE.md`, 'p1:CONTEXT.md', 'p1:PROJECT.md', 'p2:PROJECT.md'].sort()
      )
    }))

  it('lists the GitHub-only repos worth indexing, with their ids', () => {
    const s = svc(catalog(rec({ docs: { context: true, readme: false, adrCount: 0 } }), rec({ id: 'p2', repo: 'G-Eskayo/Two', docs: { context: false, readme: false, adrCount: 0 } })))
    expect(s.githubIndexRepos()).toEqual([{ name: 'P_One', id: 'p1', repo: 'G-Eskayo/P_One' }])
  })

  it('lists local folders to watch', async () =>
    withDir(async (dir) => {
      expect(svc(catalog(rec({ localPaths: [dir] }))).localDirs()).toEqual([dir])
    }))
})

// #565: a GitHub-only project reads its saved copy on every click; only opening it sends one conditional request.
describe('GitHub-only projects read the saved copy (#565)', () => {
  const ghFiles = { 'CONTEXT.md': '# ctx\n', 'README.md': '# readme\n', 'docs/adr/0001-a.md': '# A\n' }
  function counting() {
    const calls = { probe: 0, exec: 0 }
    let etag = 'W/"1"'
    const probe = async (_repo, known) => {
      calls.probe++
      if (known === etag) return { status: 304, etag }
      return { status: 200, etag, body: { tree: Object.entries(ghFiles).map(([p, t]) => ({ path: p, type: 'blob', sha: gitBlobSha(t) })) } }
    }
    const exec = vi.fn(async (_cmd, args) => {
      calls.exec++
      const p = args.find((a) => a.startsWith('repos/')).split('/contents/')[1]
      return { stdout: Buffer.from(ghFiles[p]).toString('base64') }
    })
    return { calls, probe, exec, bump: () => (etag = 'W/"2"') }
  }
  const ctxRec = () => rec({ docs: { context: true, readme: true, adrCount: 1 } })

  it('tree and content cost zero calls on every click once the copy is saved', async () =>
    withDir(async (dir) => {
      const gh = counting()
      const saved = createSavedDocs({ dir, probe: gh.probe, exec: gh.exec })
      const s = svc(catalog(ctxRec()), { exec: gh.exec, saved })
      const r = await s.revalidate('p1')
      expect(r.status).toBe('changed')
      expect(r.tree.map((e) => e.path || e.section)).toEqual(['PROJECT.md', 'CONTEXT.md', 'README.md', 'docs/adr/'])
      const n = gh.calls.probe + gh.calls.exec
      for (let i = 0; i < 10; i++) {
        const t = await s.tree('p1')
        expect(t.source).toBe('github')
        expect(t.copy.checkedAt).toBeGreaterThan(0)
        expect(await s.content('p1', 'docs/adr/0001-a.md')).toBe('# A\n')
        expect(await s.content('p1', 'PROJECT.md')).toContain('card body')
      }
      expect(gh.calls.probe + gh.calls.exec).toBe(n)
    }))

  it('before any copy exists, tree answers from the catalog with no calls and says it has no copy yet', async () =>
    withDir(async (dir) => {
      const gh = counting()
      const s = svc(catalog(ctxRec()), { exec: gh.exec, saved: createSavedDocs({ dir, probe: gh.probe, exec: gh.exec }) })
      const t = await s.tree('p1')
      expect(t.tree.map((e) => e.path)).toEqual(['PROJECT.md', 'CONTEXT.md', 'README.md'])
      expect(t.copy).toEqual({ savedAt: null, checkedAt: null })
      expect(gh.calls.probe + gh.calls.exec).toBe(0)
    }))

  it('revalidate is one conditional request per open; unchanged is a 304 with no downloads', async () =>
    withDir(async (dir) => {
      const gh = counting()
      const s = svc(catalog(ctxRec()), { exec: gh.exec, saved: createSavedDocs({ dir, probe: gh.probe, exec: gh.exec }) })
      await s.revalidate('p1')
      const exec = gh.calls.exec
      expect((await s.revalidate('p1')).status).toBe('unchanged')
      expect(gh.calls.probe).toBe(2)
      expect(gh.calls.exec).toBe(exec)
    }))

  it('local, master and card-only projects never revalidate', async () =>
    withDir(async (dir) => {
      const gh = counting()
      const saved = createSavedDocs({ dir, probe: gh.probe, exec: gh.exec })
      const s = svc(catalog(rec({ localPaths: [dir] }), rec({ id: 'p2', kind: 'local', repo: null })), { exec: gh.exec, saved })
      expect((await s.revalidate('p1')).status).toBe('not-github')
      expect((await s.revalidate('p2')).status).toBe('not-github')
      expect((await s.revalidate(MASTER_ID)).status).toBe('not-github')
      expect(gh.calls.probe).toBe(0)
    }))
})

// #570 speed budget: a local clone's tree is drawn without waiting for `git status` (75-100 ms on a real repo); the
// badges come from the last-known states, and a change is announced so the view redraws them in place.
describe('local badges come after the tree (#570)', () => {
  it('the first tree has no badges and does not wait for git; a later one has them, and the change is announced', async () =>
    withDir(async (dir) => {
      const { execFileSync } = await import('child_process')
      execFileSync('git', ['init', '-q', dir])
      writeFileSync(path.join(dir, 'CONTEXT.md'), '# ctx\n')
      const changed = []
      const s = svc(catalog(rec({ localPaths: [dir], docs: { context: true, readme: false, adrCount: 0 } })), { onStatesChanged: (id) => changed.push(id) })
      const first = await s.tree('p1')
      expect(first.tree.find((e) => e.path === 'CONTEXT.md').state).toBeNull()
      for (let i = 0; i < 50 && !changed.length; i++) await new Promise((r) => setImmediate(r)) || (await new Promise((r) => setTimeout(r, 20)))
      expect(changed).toEqual(['p1'])
      const second = await s.tree('p1')
      expect(second.tree.find((e) => e.path === 'CONTEXT.md').state).toBe('uncommitted')
    }))
})

// #611: a clone that is mid-work (dirty, another branch, ahead, diverged, mid-rebase, open in Xcode) is not
// fast-forwarded, so its search reads the GitHub saved copy instead; with no saved copy yet, its local files still count.
describe('localDocs: a mid-work clone is searched from its saved GitHub copy (#611)', () => {
  const copy = {
    tree: [{ path: 'CONTEXT.md', label: 'CONTEXT.md' }, { section: 'docs/perf/', items: [{ path: 'docs/perf/engine.md', label: 'engine.md' }] }],
    files: { 'CONTEXT.md': '# ctx from GitHub\n', 'docs/perf/engine.md': '# Engine\n\nParakeet beats Whisper here.\n' }
  }
  const saved = (c = copy) => ({ peek: (repo) => (repo === 'G-Eskayo/P_One' ? c : null) })

  it('mid-work + a saved copy: the saved copy is searched, not the stale local files', async () =>
    withDir(async (dir) => {
      writeFileSync(path.join(dir, 'CONTEXT.md'), '# ctx local\n')
      const s = svc(catalog(rec({ localPaths: [dir] })), { saved: saved(), midWork: (d) => d === dir })
      const { repos, docs } = await s.localDocs()
      expect([...repos]).toContain('p1') // the GitHub index copy of p1 must not be added a second time
      const p1 = docs.filter((d) => d.repo === 'p1' && d.path !== 'PROJECT.md')
      expect(p1.map((d) => d.path).sort()).toEqual(['CONTEXT.md', 'docs/perf/engine.md'])
      expect(p1.find((d) => d.path === 'CONTEXT.md').content).toContain('from GitHub')
      expect(p1.find((d) => d.path === 'docs/perf/engine.md').content).toContain('Parakeet')
    }))

  it('mid-work but no saved copy yet: the local files are still searched (nothing disappears)', async () =>
    withDir(async (dir) => {
      writeFileSync(path.join(dir, 'CONTEXT.md'), '# ctx local\n')
      const s = svc(catalog(rec({ localPaths: [dir] })), { saved: saved(null), midWork: () => true })
      const { docs } = await s.localDocs()
      expect(docs.find((d) => d.repo === 'p1' && d.path === 'CONTEXT.md').content).toContain('local')
    }))

  it('a saved copy with an empty tree counts as no copy', async () =>
    withDir(async (dir) => {
      writeFileSync(path.join(dir, 'CONTEXT.md'), '# ctx local\n')
      const s = svc(catalog(rec({ localPaths: [dir] })), { saved: saved({ tree: [], files: {} }), midWork: () => true })
      const { docs } = await s.localDocs()
      expect(docs.find((d) => d.repo === 'p1' && d.path === 'CONTEXT.md').content).toContain('local')
    }))

  it('a clean clone is still searched from disk', async () =>
    withDir(async (dir) => {
      writeFileSync(path.join(dir, 'CONTEXT.md'), '# ctx local\n')
      const s = svc(catalog(rec({ localPaths: [dir] })), { saved: saved(), midWork: () => false })
      const { docs } = await s.localDocs()
      expect(docs.find((d) => d.repo === 'p1' && d.path === 'CONTEXT.md').content).toContain('local')
    }))

  it('the clones to freshen are the catalog projects with a repo', () => {
    const s = svc(catalog(rec(), rec({ id: 'p2', repo: null })))
    expect(s.freshenTargets().map((p) => p.id)).toEqual(['p1'])
  })
})
