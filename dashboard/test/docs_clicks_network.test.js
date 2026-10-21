// #570 acceptance (owner, 2026-10-21): "Zero network calls on any click. Prove it with a test that counts gh / git /
// network calls through fakes." Drives the exact handler table index.js registers (docs_handlers.js) the way clicks
// do: open projects (local, GitHub-only, master, Unsorted), docs, deliverable folders and files, search results, the
// overview's headings. Every way out is counted: the injected `gh` exec, the conditional-request probe, global
// fetch, and every child_process call (git included). Temp HOME only.
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'

const childCalls = []
vi.mock('child_process', async (orig) => {
  const real = await orig()
  const wrap = (fnName) => (...args) => {
    childCalls.push([fnName, args[0], ...(Array.isArray(args[1]) ? args[1] : [])])
    return real[fnName](...args)
  }
  return { ...real, default: real, execFile: wrap('execFile'), exec: wrap('exec'), spawn: wrap('spawn'), execFileSync: wrap('execFileSync'), execSync: wrap('execSync') }
})

const NETWORK_GIT = new Set(['fetch', 'pull', 'push', 'ls-remote', 'clone', 'remote-https'])
let home, prevHome, h, counts, probe, exec, fetchSpy, docsService, docsIndexer

beforeAll(async () => {
  prevHome = process.env.HOME
  home = mkdtempSync(path.join(tmpdir(), 'clicks-home-'))
  process.env.HOME = home
  const put = (rel, data) => {
    mkdirSync(path.dirname(path.join(home, rel)), { recursive: true })
    writeFileSync(path.join(home, rel), data)
  }
  // A local clone, a GitHub-only project, and an outbox with matched, split and unsorted items.
  put('Developer/loc/CONTEXT.md', '# Loc context\n\nseal speak\n')
  put('Developer/loc/README.md', '# Loc\n')
  put('Developer/loc/docs/adr/0001-first.md', '# 1. First decision\n')
  put('.claude/outbox/loc-12-shots-2026-10-20/a.png', Buffer.from('89504e470d0a1a0a', 'hex'))
  put('.claude/outbox/loc-12-shots-2026-10-20/notes.md', '# Shot notes\n\napp store listing\n')
  put('.claude/outbox/migrations/gh1/plan.md', '# gh1 migration\n')
  put('.claude/outbox/usage_probe.py', 'print(1)\n')

  const { createSavedDocs, gitBlobSha } = await import('../electron/main/docs_saved.js')
  const { createDocsService } = await import('../electron/main/docs_service.js')
  const { createIndexer, buildDocsIndex } = await import('../electron/main/docs_search.js')
  const { createDeliverables } = await import('../electron/main/deliverables.js')
  const { docsClickHandlers, docsTextFor } = await import('../electron/main/docs_handlers.js')
  const outboxMod = await import('../electron/main/outbox.js')

  counts = { probe: 0, gh: 0 }
  const ghFiles = { 'README.md': '# gh1\n', 'docs/adr/0002-x.md': '# 2. X\n' }
  probe = async (_repo, etag) => {
    counts.probe++
    return etag === 'e1' ? { status: 304, etag } : { status: 200, etag: 'e1', body: { tree: Object.entries(ghFiles).map(([p, t]) => ({ path: p, type: 'blob', sha: gitBlobSha(t) })) } }
  }
  exec = async (_cmd, args) => {
    counts.gh++
    const p = args.find((a) => a.startsWith('repos/')).split('/contents/')[1]
    return { stdout: Buffer.from(ghFiles[p]).toString('base64') }
  }
  fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    throw new Error('network is not allowed in this test')
  })

  const projects = [
    { id: 'loc', name: 'loc', kind: 'repo', repo: 'G-Eskayo/loc', status: 'active', localPaths: [path.join(home, 'Developer/loc')], docs: { context: true, readme: true, adrCount: 1 }, summary_md: '# loc\n' },
    { id: 'gh1', name: 'gh1', kind: 'repo', repo: 'G-Eskayo/gh1', status: 'active', localPaths: [], docs: { context: false, readme: true, adrCount: 1 }, summary_md: '# gh1\n' }
  ]
  const catalog = { generated_at: '2026-10-21T00:00:00Z', projects }
  const saved = createSavedDocs({ dir: path.join(home, '.claude/logs/docs-github'), probe, exec })
  const deliverables = createDeliverables({
    getContext: () => ({ projects, overrides: {}, maxNumber: { 'G-Eskayo/loc': 40 }, docsText: docsTextFor(projects, { saved }) }),
    cachePath: path.join(home, '.claude/logs/outbox-matches.json')
  })
  docsService = createDocsService({ getCatalog: () => catalog, exec, readMaster: () => '# Where things are\n', saved, deliverables })
  docsIndexer = createIndexer({
    build: () => buildDocsIndex(exec, docsService.githubIndexRepos(), path.join(home, '.claude/logs/idx.json'), { saved, offline: true }),
    getLocal: () => docsService.localDocs()
  })
  const outbox = { list: outboxMod.listOutboxDir, summary: outboxMod.summarizeOutbox, preview: outboxMod.outboxPreview, content: outboxMod.readOutboxFile, image: outboxMod.readOutboxImage }
  h = docsClickHandlers({ docsService, docsIndexer, outbox })

  // Opening the GitHub-only project once: the open-time check fills its saved copy. Not a click; counted below.
  deliverables.refresh()
  await docsService.revalidate('gh1')
})

afterAll(() => {
  fetchSpy?.mockRestore()
  process.env.HOME = prevHome
  rmSync(home, { recursive: true, force: true })
})

const networkGit = () => childCalls.filter(([, cmd, ...args]) => cmd === 'git' && args.some((a) => NETWORK_GIT.has(a)))
const ghChild = () => childCalls.filter(([, cmd]) => cmd === 'gh' || String(cmd).endsWith('/gh'))

describe('zero network calls on any click (#570)', () => {
  it('the open-time check of a GitHub-only project is one conditional request', () => {
    expect(counts.probe).toBe(1)
  })

  it('every click in the Docs tab, ten rounds: 0 gh, 0 probe, 0 fetch, 0 network git', async () => {
    const before = { ...counts }
    const fetchesBefore = fetchSpy.mock.calls.length
    const childBefore = childCalls.length
    for (let round = 0; round < 10; round++) {
      const { repos } = await h['docs:repos']()
      for (const r of repos) {
        const t = await h['docs:tree'](r.id)
        for (const e of t.tree.flatMap((x) => (x.section ? x.items : [x]))) await h['docs:content'](r.id, e.path)
        await h['docs:headings'](r.id, t.tree.flatMap((x) => (x.section ? x.items : [x])).map((e) => e.path))
        for (const d of [...(t.deliverables || []), ...(t.leftovers || []).flatMap((l) => l.entries)]) {
          if (d.isDir) {
            const { entries } = await h['outbox:list'](d.path)
            for (const c of entries) {
              await h['outbox:summary'](c.path)
              if (c.type === 'file') {
                await h['outbox:preview'](c.path)
                await h['outbox:content'](c.path)
              }
            }
          } else await h['outbox:content'](d.path)
        }
      }
      for (const q of ['seal speak', 'shot notes', 'first decision', 'app store', 'gh1']) {
        const s = await h['docs:search'](q)
        for (const res of s.results) {
          if (res.kind === 'deliverable') {
            if (!res.isDir) await h['outbox:content'](res.path.replace(/^outbox\//, ''))
          } else await h['docs:content'](res.repo, res.path)
        }
      }
      await h['outbox:image']('loc-12-shots-2026-10-20/notes.md', 'a.png')
    }
    expect(counts).toEqual(before)
    expect(fetchSpy.mock.calls.length).toBe(fetchesBefore)
    expect(networkGit()).toEqual([])
    expect(ghChild()).toEqual([])
    // What did leave the process is local git only (the uncommitted/unpushed badges), never a network subcommand.
    const during = childCalls.slice(childBefore)
    expect(during.filter(([, cmd]) => cmd !== 'git')).toEqual([])
    expect(during.length).toBeGreaterThan(0) // the child_process fake really sees calls
    expect(new Set(during.map(([, , , , sub]) => sub))).toEqual(new Set(['status', 'diff']))
  })

  it('the clicks really reached deliverables, decisions and the saved copy (the test is not vacuous)', async () => {
    const loc = await h['docs:tree']('loc')
    expect(loc.deliverables.map((d) => d.path)).toContain('loc-12-shots-2026-10-20')
    const gh = await h['docs:tree']('gh1')
    expect(gh.tree.flatMap((x) => (x.section ? x.items : [x])).map((e) => e.path)).toContain('docs/adr/0002-x.md')
    expect(gh.deliverables.map((d) => d.path)).toEqual(['migrations/gh1'])
    expect(await h['docs:content']('gh1', 'docs/adr/0002-x.md')).toBe('# 2. X\n')
    const uns = await h['docs:tree']('__unsorted__')
    expect(uns.deliverables.map((d) => d.path)).toEqual(['usage_probe.py'])
    const s = await h['docs:search']('shot notes')
    expect(s.results.some((r) => r.kind === 'deliverable' && r.repo === 'loc')).toBe(true)
    expect(s.deliverableCount).toBeGreaterThan(0)
    expect((await h['docs:headings']('loc', ['docs/adr/0001-first.md']))['docs/adr/0001-first.md']).toBe('1. First decision')
  })

  it('re-opening the GitHub-only project is one more conditional request, answered 304, and no download', async () => {
    const gh = counts.gh
    expect((await docsService.revalidate('gh1')).status).toBe('unchanged')
    expect(counts.probe).toBe(2)
    expect(counts.gh).toBe(gh)
  })
})
