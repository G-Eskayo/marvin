import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync, readFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { discoverDocFirstRepos, readCachedRepos, listRepoDocTree, fetchFileContent } from '../electron/main/docs.js'

// Fakes `gh`'s shape: execFileAsync('gh', [...args]) -> { stdout }.
function fakeExec(responses) {
  return vi.fn(async (_cmd, args) => {
    const key = args.join(' ')
    for (const [match, result] of responses) {
      if (key.includes(match)) {
        if (result instanceof Error) throw result
        return { stdout: result }
      }
    }
    throw new Error(`fakeExec: no response configured for: ${key}`)
  })
}

function withTempCachePath(fn) {
  const dir = mkdtempSync(path.join(tmpdir(), 'docs-cache-test-'))
  const cachePath = path.join(dir, 'doc-repos-cache.json')
  return Promise.resolve(fn(cachePath)).finally(() => rmSync(dir, { recursive: true, force: true }))
}

describe('discoverDocFirstRepos', () => {
  it('keeps only repos that actually have a CONTEXT.md', () =>
    withTempCachePath(async (cachePath) => {
      const execFileAsync = fakeExec([
        ['repo list', JSON.stringify([
          { name: 'marvin', description: '', pushedAt: '2026-10-01T00:00:00Z', isArchived: false },
          { name: 'no-context-md', description: '', pushedAt: '2026-09-01T00:00:00Z', isArchived: false }
        ])],
        ['repos/G-Eskayo/marvin/contents/CONTEXT.md', 'CONTEXT.md'],
        ['repos/G-Eskayo/no-context-md/contents/CONTEXT.md', new Error('404')]
      ])
      const repos = await discoverDocFirstRepos(execFileAsync, cachePath)
      expect(repos.map((r) => r.name)).toEqual(['marvin'])
      expect(repos[0].hasContext).toBeUndefined() // internal flag stripped before returning
      // also written to the cache file, not just returned
      const cached = JSON.parse(readFileSync(cachePath, 'utf-8'))
      expect(cached.repos.map((r) => r.name)).toEqual(['marvin'])
    }))

  it('excludes archived repos', () =>
    withTempCachePath(async (cachePath) => {
      const execFileAsync = fakeExec([
        ['repo list', JSON.stringify([
          { name: 'old-thing', description: '', pushedAt: '2024-01-01T00:00:00Z', isArchived: true }
        ])]
      ])
      const repos = await discoverDocFirstRepos(execFileAsync, cachePath)
      expect(repos).toEqual([])
    }))
})

describe('readCachedRepos', () => {
  it('returns an empty shape when no cache file exists yet', () =>
    withTempCachePath((cachePath) => {
      expect(readCachedRepos(cachePath)).toEqual({ generated_at: null, repos: [] })
    }))
})

describe('listRepoDocTree', () => {
  it('always includes CONTEXT.md, adds README.md and docs/adr/ only if present', async () => {
    const execFileAsync = fakeExec([
      ['contents/README.md', 'README.md'],
      ['contents/docs/adr', JSON.stringify([
        { name: '0002-foo.md', type: 'file' },
        { name: '0001-bar.md', type: 'file' },
        { name: 'not-markdown.txt', type: 'file' },
        { name: 'subdir', type: 'dir' }
      ])]
    ])
    const tree = await listRepoDocTree(execFileAsync, 'marvin')
    expect(tree[0]).toEqual({ path: 'CONTEXT.md', label: 'CONTEXT.md' })
    expect(tree[1]).toEqual({ path: 'README.md', label: 'README.md' })
    expect(tree[2].section).toBe('docs/adr/')
    // sorted by filename, non-.md and directories excluded
    expect(tree[2].items).toEqual([
      { path: 'docs/adr/0001-bar.md', label: '0001-bar.md' },
      { path: 'docs/adr/0002-foo.md', label: '0002-foo.md' }
    ])
  })

  it('omits docs/adr section entirely when the repo has none yet', async () => {
    const execFileAsync = fakeExec([
      ['contents/README.md', new Error('404')],
      ['contents/docs/adr', new Error('404')]
    ])
    const tree = await listRepoDocTree(execFileAsync, 'brand-new-repo')
    expect(tree).toEqual([{ path: 'CONTEXT.md', label: 'CONTEXT.md' }])
  })
})

describe('fetchFileContent', () => {
  it('decodes base64 content from the GitHub API, tolerating embedded newlines', async () => {
    const original = '# Hello\n\nSome real markdown content with enough length to wrap.'
    const b64 = Buffer.from(original, 'utf-8').toString('base64')
    const wrapped = b64.match(/.{1,20}/g).join('\n') // simulate GitHub's wrapped base64
    const execFileAsync = fakeExec([['contents/CONTEXT.md', wrapped]])
    const content = await fetchFileContent(execFileAsync, 'marvin', 'CONTEXT.md')
    expect(content).toBe(original)
  })
})
