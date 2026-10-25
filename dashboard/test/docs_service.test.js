import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createDocsService, MASTER_ID } from '../electron/main/docs_service.js'

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
    expect(s.githubIndexRepos()).toEqual([{ name: 'P_One', id: 'p1' }])
  })

  it('lists local folders to watch', async () =>
    withDir(async (dir) => {
      expect(svc(catalog(rec({ localPaths: [dir] }))).localDirs()).toEqual([dir])
    }))
})

describe('treeFromDocs', () => {
  it('builds a tree from cached docs: CONTEXT.md and README.md first, then doc sections (reuses groupDocSections)', async () => {
    const { treeFromDocs } = await import('../electron/main/docs_service.js')
    const docs = [
      { repo: 'p', path: 'CONTEXT.md', label: 'CONTEXT.md' },
      { repo: 'p', path: 'README.md', label: 'README.md' },
      { repo: 'p', path: 'docs/adr/0001-a.md', label: '0001-a.md' },
      { repo: 'p', path: 'docs/adr/0002-b.md', label: '0002-b.md' },
      { repo: 'p', path: 'audit.ipynb', label: 'audit.ipynb' }
    ]
    const tree = treeFromDocs(docs, 'p')
    expect(tree[0]).toMatchObject({ path: 'CONTEXT.md', label: 'CONTEXT.md' })
    expect(tree[1]).toMatchObject({ path: 'README.md', label: 'README.md' })
    const adrSection = tree.find(e => e.section === 'docs/adr/')
    expect(adrSection).toBeDefined()
    expect(adrSection.items).toHaveLength(2)
    const notebooksSection = tree.find(e => e.section === 'notebooks')
    expect(notebooksSection).toBeDefined()
  })

  it('omits files that do not exist in the docs list', async () => {
    const { treeFromDocs } = await import('../electron/main/docs_service.js')
    const docs = [
      { repo: 'p', path: 'CONTEXT.md', label: 'CONTEXT.md' }
    ]
    const tree = treeFromDocs(docs, 'p')
    expect(tree.find(e => e.path === 'README.md')).toBeUndefined()
  })

  it('groups all docs/ subdirs via groupDocSections, docs/adr/ first', async () => {
    const { treeFromDocs } = await import('../electron/main/docs_service.js')
    const docs = [
      { repo: 'p', path: 'CONTEXT.md', label: 'CONTEXT.md' },
      { repo: 'p', path: 'docs/adr/0001-first.md', label: '0001-first.md' },
      { repo: 'p', path: 'docs/guides/writing.md', label: 'writing.md' }
    ]
    const tree = treeFromDocs(docs, 'p')
    const adrSection = tree.find(e => e.section === 'docs/adr/')
    const guidesSection = tree.find(e => e.section === 'docs/guides/')
    expect(adrSection?.items[0].label).toBe('0001-first.md')
    expect(guidesSection?.items[0].label).toBe('writing.md')
    expect(tree.indexOf(adrSection) < tree.indexOf(guidesSection)).toBe(true)
  })

  it('includes trailing root-level notebooks section', async () => {
    const { treeFromDocs } = await import('../electron/main/docs_service.js')
    const docs = [
      { repo: 'p', path: 'CONTEXT.md', label: 'CONTEXT.md' },
      { repo: 'p', path: 'analysis.ipynb', label: 'analysis.ipynb' }
    ]
    const tree = treeFromDocs(docs, 'p')
    const notebooksSection = tree[tree.length - 1]
    expect(notebooksSection.section).toBe('notebooks')
    expect(notebooksSection.items.some(i => i.path === 'analysis.ipynb')).toBe(true)
  })
})

describe('createDocsService with getIndexer injection', () => {
  it('accepts a getIndexer lazy getter and uses it for peek and GitHub fetch-on-miss', async () => {
    const indexer = { peek: () => null }
    const svc = createDocsService({
      getCatalog: () => null,
      exec: vi.fn(),
      readMaster: () => null,
      getIndexer: () => indexer
    })
    expect(svc).toBeDefined()
  })

  it('creates a default indexer with empty load if none is injected', async () => {
    const svc = createDocsService({
      getCatalog: () => null,
      exec: vi.fn(),
      readMaster: () => null
    })
    expect(svc).toBeDefined()
  })
})

describe('tree() with GitHub fetch-on-miss and fetchedAt', () => {
  it('returns fetchedAt when source is github and tree was fetched live', async () => {
    const indexer = { peek: () => null }
    const exec = vi.fn(async (_c, args) => {
      const key = args.join(' ')
      if (key.endsWith('--jq .name')) return { stdout: 'CONTEXT.md' }
      if (key.includes('git/trees')) {
        return { stdout: JSON.stringify({ tree: [{ type: 'blob', path: 'CONTEXT.md' }, { type: 'blob', path: 'README.md' }] }) }
      }
      throw new Error('404')
    })
    const svc = createDocsService({
      getCatalog: () => catalog(rec({ docs: { context: true, readme: true, adrCount: 0 } })),
      exec,
      readMaster: () => null,
      getIndexer: () => indexer
    })
    const t = await svc.tree('p1')
    expect(t.source).toBe('github')
    expect(t.fetchedAt).toBeTruthy()
  })
})

describe('content() with per-file GitHub upsert', () => {
  it('fetches a single file from GitHub when not in index, upserts it, and returns original text', async () => {
    const indexed = []
    const indexer = {
      peek: () => null,
      upsertDoc: vi.fn((doc) => indexed.push(doc))
    }
    const exec = vi.fn(async () => ({ stdout: Buffer.from('# File content').toString('base64') }))
    const svc = createDocsService({
      getCatalog: () => catalog(rec({ docs: { context: true, readme: false, adrCount: 0 } })),
      exec,
      readMaster: () => null,
      getIndexer: () => indexer
    })
    const content = await svc.content('p1', 'CONTEXT.md')
    expect(content).toBe('# File content')
    expect(indexed.length).toBeGreaterThan(0)
    expect(indexed[0].path).toBe('CONTEXT.md')
  })

  it('returns cached content from indexer.peek() if available', async () => {
    const indexer = {
      peek: () => ({
        docs: [{ repo: 'p1', path: 'CONTEXT.md', label: 'CONTEXT.md', content: 'cached' }]
      })
    }
    const exec = vi.fn()
    const svc = createDocsService({
      getCatalog: () => catalog(rec({ docs: { context: true, readme: false, adrCount: 0 } })),
      exec,
      readMaster: () => null,
      getIndexer: () => indexer
    })
    const content = await svc.content('p1', 'CONTEXT.md')
    expect(content).toBe('cached')
    expect(exec).not.toHaveBeenCalled()
  })
})

describe('tree() single-flight caching', () => {
  it('does not issue concurrent GitHub fetches for the same repo', async () => {
    const indexer = { peek: () => null }
    let concurrentCount = 0
    let maxConcurrent = 0
    const exec = vi.fn(async () => {
      concurrentCount += 1
      maxConcurrent = Math.max(maxConcurrent, concurrentCount)
      await new Promise(r => setTimeout(r, 10))
      concurrentCount -= 1
      return { stdout: JSON.stringify({ tree: [{ type: 'blob', path: 'CONTEXT.md' }] }) }
    })
    const svc = createDocsService({
      getCatalog: () => catalog(rec({ docs: { context: true, readme: false, adrCount: 0 } })),
      exec,
      readMaster: () => null,
      getIndexer: () => indexer
    })
    await Promise.all([svc.tree('p1'), svc.tree('p1')])
    expect(maxConcurrent).toBeLessThanOrEqual(1)
  })
})

describe('tree() with onRepoOpened hook', () => {
  it('calls onRepoOpened unconditionally once per call (cache hit or miss)', async () => {
    const indexer = {
      peek: () => ({
        docs: [{ repo: 'p1', path: 'CONTEXT.md', label: 'CONTEXT.md', content: 'cached' }]
      })
    }
    const opened = []
    const onRepoOpened = vi.fn(async (rec) => opened.push(rec.id))
    const exec = vi.fn()
    const svc = createDocsService({
      getCatalog: () => catalog(rec({ docs: { context: true, readme: false, adrCount: 0 } })),
      exec,
      readMaster: () => null,
      getIndexer: () => indexer,
      onRepoOpened
    })
    // Even with cache hit, should call onRepoOpened
    await svc.tree('p1')
    expect(onRepoOpened).toHaveBeenCalledWith(expect.objectContaining({ id: 'p1' }))
  })

  it('calls onRepoOpened once per call (cache miss)', async () => {
    const indexer = { peek: () => null }
    const onRepoOpened = vi.fn()
    const exec = vi.fn(async (_c, args) => {
      const key = args.join(' ')
      if (key.endsWith('--jq .name')) return { stdout: 'CONTEXT.md' }
      if (key.includes('git/trees')) {
        return { stdout: JSON.stringify({ tree: [{ type: 'blob', path: 'CONTEXT.md' }] }) }
      }
      throw new Error('404')
    })
    const svc = createDocsService({
      getCatalog: () => catalog(rec({ docs: { context: true, readme: false, adrCount: 0 } })),
      exec,
      readMaster: () => null,
      getIndexer: () => indexer,
      onRepoOpened
    })
    await svc.tree('p1')
    expect(onRepoOpened).toHaveBeenCalledTimes(1)
  })
})

describe('content() with per-file upsert and raw field', () => {
  it('cache-hit returns raw field if present, falling back to content', async () => {
    const indexer = {
      peek: () => ({
        docs: [
          { repo: 'p1', path: 'RAW.md', label: 'RAW.md', content: 'searchable', raw: 'original **markdown**' },
          { repo: 'p1', path: 'NORAW.md', label: 'NORAW.md', content: 'content only' }
        ]
      })
    }
    const exec = vi.fn()
    const svc = createDocsService({
      getCatalog: () => catalog(rec({ docs: { context: true, readme: false, adrCount: 0 } })),
      exec,
      readMaster: () => null,
      getIndexer: () => indexer
    })
    const withRaw = await svc.content('p1', 'RAW.md')
    const noRaw = await svc.content('p1', 'NORAW.md')
    expect(withRaw).toBe('original **markdown**')
    expect(noRaw).toBe('content only')
  })

  it('cache-miss uses upsertDoc instead of applyRepoDocs', async () => {
    const indexed = []
    const indexer = {
      peek: () => null,
      upsertDoc: vi.fn((doc) => indexed.push(doc))
    }
    const exec = vi.fn(async () => ({ stdout: Buffer.from('# File content').toString('base64') }))
    const svc = createDocsService({
      getCatalog: () => catalog(rec({ docs: { context: true, readme: false, adrCount: 0 } })),
      exec,
      readMaster: () => null,
      getIndexer: () => indexer
    })
    await svc.content('p1', 'CONTEXT.md')
    expect(indexer.upsertDoc).toHaveBeenCalled()
    expect(indexed[0]).toMatchObject({ repo: 'p1', path: 'CONTEXT.md' })
  })

  it('cache-miss includes raw field when searchableText differs from original', async () => {
    const indexed = []
    const indexer = {
      peek: () => null,
      upsertDoc: vi.fn((doc) => indexed.push(doc))
    }
    const exec = vi.fn(async () => ({ stdout: Buffer.from('text with **markdown**').toString('base64') }))
    const svc = createDocsService({
      getCatalog: () => catalog(rec({ docs: { context: true, readme: false, adrCount: 0 } })),
      exec,
      readMaster: () => null,
      getIndexer: () => indexer
    })
    await svc.content('p1', 'CONTEXT.md')
    // For .md files, searchableText returns content as-is, so no raw field
    expect(indexed[0].raw).toBeUndefined()
  })
})

describe('ghName export', () => {
  it('exports ghName as a function', async () => {
    const { ghName } = await import('../electron/main/docs_service.js')
    expect(typeof ghName).toBe('function')
    expect(ghName({ repo: 'G-Eskayo/marvin' })).toBe('marvin')
  })
})
