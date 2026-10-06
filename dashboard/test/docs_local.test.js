import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'fs'
import { execFileSync } from 'child_process'
import { tmpdir } from 'os'
import path from 'path'
import { resolveLocalClone, listLocalTree, readLocalFile, localFileStates } from '../electron/main/docs_local.js'

const git = (dir, ...args) => execFileSync('git', ['-C', dir, ...args], { encoding: 'utf-8', env: { ...process.env, GIT_AUTHOR_NAME: 't', GIT_AUTHOR_EMAIL: 't@t', GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@t' } }).trim()

function makeRepo(root, name, { origin = `https://github.com/G-Eskayo/${name}.git`, date = '2026-10-01T00:00:00' } = {}) {
  const dir = path.join(root, name)
  mkdirSync(path.join(dir, 'docs', 'adr'), { recursive: true })
  git(dir, 'init', '-q', '-b', 'main')
  git(dir, 'remote', 'add', 'origin', origin)
  writeFileSync(path.join(dir, 'CONTEXT.md'), '# ctx\n')
  writeFileSync(path.join(dir, 'docs', 'adr', '0002-b.md'), 'b')
  writeFileSync(path.join(dir, 'docs', 'adr', '0001-a.md'), 'a')
  git(dir, 'add', '.')
  execFileSync('git', ['-C', dir, 'commit', '-q', '-m', 'init', '--date', date], { env: { ...process.env, GIT_AUTHOR_NAME: 't', GIT_AUTHOR_EMAIL: 't@t', GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@t', GIT_COMMITTER_DATE: date } })
  git(dir, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
  return dir
}

const withRoot = async (fn) => {
  const root = mkdtempSync(path.join(tmpdir(), 'docslocal-'))
  try {
    return await fn(root)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
}

describe('resolveLocalClone', () => {
  it('finds the clone whose origin is the repo', () =>
    withRoot(async (root) => {
      const dir = makeRepo(root, 'proj')
      makeRepo(root, 'other')
      expect(await resolveLocalClone('proj', { candidateDirs: [path.join(root, 'other'), dir] })).toBe(dir)
    }))

  it('returns null when no candidate matches', () =>
    withRoot(async (root) => {
      makeRepo(root, 'other')
      expect(await resolveLocalClone('proj', { candidateDirs: [path.join(root, 'other'), path.join(root, 'missing')] })).toBeNull()
    }))

  it('with several clones, picks the one whose HEAD commit is newest', () =>
    withRoot(async (root) => {
      mkdirSync(path.join(root, 'a'))
      mkdirSync(path.join(root, 'b'))
      const old = makeRepo(path.join(root, 'a'), 'proj', { date: '2026-09-01T00:00:00' })
      const fresh = makeRepo(path.join(root, 'b'), 'proj', { date: '2026-10-05T00:00:00' })
      expect(await resolveLocalClone('proj', { candidateDirs: [old, fresh] })).toBe(fresh)
    }))
})

describe('listLocalTree / readLocalFile', () => {
  it('lists CONTEXT.md, README.md when present, and sorted adr files', () =>
    withRoot((root) => {
      const dir = makeRepo(root, 'proj')
      const tree = listLocalTree(dir)
      expect(tree[0]).toEqual({ path: 'CONTEXT.md', label: 'CONTEXT.md' })
      expect(tree.find((e) => e.section).items.map((i) => i.label)).toEqual(['0001-a.md', '0002-b.md'])
      expect(tree.some((e) => e.path === 'README.md')).toBe(false)
    }))

  it('reads docs but refuses anything outside the doc set or outside the repo', () =>
    withRoot((root) => {
      const dir = makeRepo(root, 'proj')
      writeFileSync(path.join(root, 'secret.md'), 'nope')
      expect(readLocalFile(dir, 'CONTEXT.md')).toBe('# ctx\n')
      expect(() => readLocalFile(dir, '../secret.md')).toThrow()
      expect(() => readLocalFile(dir, 'package.json')).toThrow()
      expect(() => readLocalFile(dir, 'docs/adr/../../../secret.md')).toThrow()
    }))
})

describe('localFileStates', () => {
  it('marks modified and untracked docs as uncommitted, committed-ahead ones as unpushed', () =>
    withRoot(async (root) => {
      const dir = makeRepo(root, 'proj')
      writeFileSync(path.join(dir, 'CONTEXT.md'), '# ctx changed\n') // modified, uncommitted
      writeFileSync(path.join(dir, 'README.md'), 'new') // untracked
      writeFileSync(path.join(dir, 'docs', 'adr', '0001-a.md'), 'a2')
      git(dir, 'add', 'docs')
      git(dir, 'commit', '-q', '-m', 'adr') // committed but ahead of origin/main
      const states = await localFileStates(dir)
      expect(states['CONTEXT.md']).toBe('uncommitted')
      expect(states['README.md']).toBe('uncommitted')
      expect(states['docs/adr/0001-a.md']).toBe('unpushed')
      expect(states['docs/adr/0002-b.md']).toBeUndefined()
    }))
})


describe('notebooks in the local doc tree', () => {
  it('lists root-level .ipynb files and allows reading them, but not other paths', () =>
    withRoot(async (root) => {
      const dir = makeRepo(root, 'proj')
      writeFileSync(path.join(dir, 'b.ipynb'), '{"cells": []}')
      writeFileSync(path.join(dir, 'a.ipynb'), '{"cells": []}')
      writeFileSync(path.join(dir, 'data.csv'), 'x')
      const section = listLocalTree(dir).find((e) => e.section === 'notebooks')
      expect(section.items.map((i) => i.path)).toEqual(['a.ipynb', 'b.ipynb'])
      expect(readLocalFile(dir, 'a.ipynb')).toBe('{"cells": []}')
      expect(() => readLocalFile(dir, 'data.csv')).toThrow()
      expect(() => readLocalFile(dir, '../a.ipynb')).toThrow()
    }))
})

describe('everything under docs/, not only docs/adr/', () => {
  // The Docs tab used to list only docs/adr/, so audits, guides and write-ups under docs/ were invisible.
  const addDocs = (dir) => {
    for (const [rel, text] of [
      ['docs/audits/content-audit-2026-10-06.md', '# audit'],
      ['docs/overview.md', '# overview'],
      ['docs/agents/issue-tracker.md', '# tracker'],
      ['docs/audits/figure.png', 'not markdown'],
      ['docs/.cache/hidden.md', 'hidden folder']
    ]) {
      mkdirSync(path.dirname(path.join(dir, rel)), { recursive: true })
      writeFileSync(path.join(dir, rel), text)
    }
  }

  it('lists every .md under docs/ grouped by folder, docs/adr/ first, skipping hidden folders and non-markdown', () =>
    withRoot((root) => {
      const dir = makeRepo(root, 'proj')
      addDocs(dir)
      const sections = listLocalTree(dir).filter((e) => e.section)
      expect(sections.map((s) => s.section)).toEqual(['docs/adr/', 'docs/', 'docs/agents/', 'docs/audits/'])
      expect(sections.find((s) => s.section === 'docs/audits/').items).toEqual([
        { path: 'docs/audits/content-audit-2026-10-06.md', label: 'content-audit-2026-10-06.md' }
      ])
      expect(sections.find((s) => s.section === 'docs/').items.map((i) => i.path)).toEqual(['docs/overview.md'])
      expect(JSON.stringify(sections)).not.toContain('hidden.md')
    }))

  it('reads any .md under docs/, but still refuses non-markdown, hidden folders and escapes', () =>
    withRoot((root) => {
      const dir = makeRepo(root, 'proj')
      addDocs(dir)
      expect(readLocalFile(dir, 'docs/audits/content-audit-2026-10-06.md')).toBe('# audit')
      expect(readLocalFile(dir, 'docs/overview.md')).toBe('# overview')
      expect(() => readLocalFile(dir, 'docs/audits/figure.png')).toThrow()
      expect(() => readLocalFile(dir, 'docs/.cache/hidden.md')).toThrow()
      expect(() => readLocalFile(dir, 'docs/../CONTEXT.md.bak')).toThrow()
      expect(() => readLocalFile(dir, 'docs/audits/../../../etc/x.md')).toThrow()
    }))

  it('marks a new, never-committed write-up under docs/ as uncommitted', () =>
    withRoot(async (root) => {
      const dir = makeRepo(root, 'proj')
      addDocs(dir)
      expect((await localFileStates(dir))['docs/audits/content-audit-2026-10-06.md']).toBe('uncommitted')
    }))
})
