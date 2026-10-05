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
