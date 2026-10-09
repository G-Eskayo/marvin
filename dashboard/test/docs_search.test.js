import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { extractOutline, splitSections } from '../src/lib/docs_text.js'
import { searchDocs, buildDocsIndex, loadIndex, isStale } from '../electron/main/docs_search.js'

const MD = `# Title

intro text

## Boards

Columns derive from labels.

\`\`\`
# not a heading
\`\`\`

### Blocked

Blocked by #7.

## Triggers

Watch files.
`

describe('extractOutline', () => {
  it('lists headings in order with level and text, skipping code fences', () => {
    expect(extractOutline(MD).map((h) => [h.level, h.text])).toEqual([
      [1, 'Title'],
      [2, 'Boards'],
      [3, 'Blocked'],
      [2, 'Triggers']
    ])
  })

  it('gives each heading its index in document order', () => {
    expect(extractOutline(MD).map((h) => h.index)).toEqual([0, 1, 2, 3])
  })

  it('strips inline markdown from heading text', () => {
    expect(extractOutline('## The `board` **view** [x](u)\n')[0].text).toBe('The board view x')
  })
})

describe('splitSections', () => {
  it('splits on headings, keeping preamble text under index -1', () => {
    const s = splitSections('pre\n\n# A\n\na body\n\n## B\n\nb body\n')
    expect(s.map((x) => [x.headingIndex, x.heading])).toEqual([[-1, ''], [0, 'A'], [1, 'B']])
    expect(s[1].text).toContain('a body')
  })
})

const index = {
  generated_at: '2026-10-05T00:00:00Z',
  docs: [
    { repo: 'marvin', path: 'CONTEXT.md', label: 'CONTEXT.md', content: MD },
    { repo: 'marvin', path: 'docs/adr/0033-health.md', label: '0033-health.md', content: '# Health coverage\n\nTriggers are watched by the health tab.\n' },
    { repo: 'other', path: 'CONTEXT.md', label: 'CONTEXT.md', content: '# Other\n\nnothing relevant\n' }
  ]
}

describe('searchDocs', () => {
  it('finds a section and returns its repo, file, heading and snippet', () => {
    const r = searchDocs(index, 'watch files')
    expect(r[0]).toMatchObject({ repo: 'marvin', path: 'CONTEXT.md', heading: 'Triggers', headingIndex: 3 })
    expect(r[0].snippet.toLowerCase()).toContain('watch files')
  })

  it('requires every term within the same section', () => {
    expect(searchDocs(index, 'columns watch')).toEqual([])
    expect(searchDocs(index, 'columns labels')[0].heading).toBe('Boards')
  })

  it('is case-insensitive and ignores empty queries', () => {
    expect(searchDocs(index, 'BLOCKED BY').length).toBe(1)
    expect(searchDocs(index, '   ')).toEqual([])
  })

  it('ranks a heading hit above a body-only hit', () => {
    const r = searchDocs(index, 'triggers')
    expect(r[0].heading).toBe('Triggers')
    expect(r.map((x) => x.path)).toContain('docs/adr/0033-health.md')
  })

  it('can be limited to one repo and respects the result limit', () => {
    expect(searchDocs(index, 'title', { repo: 'other' })).toEqual([])
    expect(searchDocs(index, 'the', { limit: 1 }).length).toBe(1)
  })

  it('returns the terms so the UI can highlight them', () => {
    expect(searchDocs(index, 'Watch files')[0].terms).toEqual(['watch', 'files'])
  })
})

function fakeExec() {
  return vi.fn(async (_c, args) => {
    const key = args.join(' ')
    if (key.endsWith('contents/CONTEXT.md --jq .content')) return { stdout: Buffer.from('# Ctx\n\nhello\n').toString('base64') }
    if (key.endsWith('contents/README.md --jq .name')) throw new Error('404')
    if (key.endsWith('contents/CONTEXT.md --jq .name')) return { stdout: 'CONTEXT.md' }
    if (key.includes('contents/docs/adr')) throw new Error('404')
    throw new Error(`unexpected: ${key}`)
  })
}

describe('buildDocsIndex / loadIndex', () => {
  it('fetches every browsable file of every repo and persists the index', async () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'docsidx-'))
    try {
      const file = path.join(dir, 'idx.json')
      const built = await buildDocsIndex(fakeExec(), [{ name: 'marvin' }], file)
      expect(built.docs).toEqual([{ repo: 'marvin', path: 'CONTEXT.md', label: 'CONTEXT.md', content: '# Ctx\n\nhello\n' }])
      expect(loadIndex(file).docs.length).toBe(1)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('keeps going when one file fails to fetch', async () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'docsidx-'))
    try {
      const exec = vi.fn(async (_c, args) => {
        const key = args.join(' ')
        if (key.includes('--jq .content')) throw new Error('boom')
        if (key.endsWith('--jq .name') && key.includes('CONTEXT.md')) return { stdout: 'CONTEXT.md' }
        throw new Error('404')
      })
      const built = await buildDocsIndex(exec, [{ name: 'marvin' }], path.join(dir, 'i.json'))
      expect(built.docs).toEqual([])
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('loadIndex returns an empty index for a missing or corrupt file', () => {
    expect(loadIndex('/nonexistent/x.json')).toEqual({ generated_at: null, docs: [] })
  })

  it('isStale is true when missing or older than the max age', () => {
    expect(isStale({ generated_at: null, docs: [] })).toBe(true)
    expect(isStale({ generated_at: new Date().toISOString(), docs: [] }, 60_000)).toBe(false)
    expect(isStale({ generated_at: new Date(Date.now() - 120_000).toISOString(), docs: [] }, 60_000)).toBe(true)
  })
})

import { createIndexer } from '../electron/main/docs_search.js'

describe('createIndexer', () => {
  const doc = { repo: 'm', path: 'CONTEXT.md', label: 'CONTEXT.md', content: '# A\n\nneedle here\n' }

  it('builds on the first search when there is no index, then answers from it', async () => {
    const build = vi.fn(async () => ({ generated_at: new Date().toISOString(), docs: [doc] }))
    const ix = createIndexer({ build, load: () => ({ generated_at: null, docs: [] }) })
    const out = await ix.search('needle')
    expect(build).toHaveBeenCalledTimes(1)
    expect(out.results[0].heading).toBe('A')
    expect(out.docCount).toBe(1)
  })

  it('answers a stale index immediately and rebuilds once in the background', async () => {
    const stale = { generated_at: '2020-01-01T00:00:00Z', docs: [doc] }
    let release
    const build = vi.fn(() => new Promise((r) => (release = () => r({ generated_at: new Date().toISOString(), docs: [doc] }))))
    const ix = createIndexer({ build, load: () => stale })
    const a = await ix.search('needle')
    await ix.search('needle')
    expect(a.results.length).toBe(1)
    expect(a.indexing).toBe(true)
    expect(build).toHaveBeenCalledTimes(1) // single-flight
    release()
  })

  it('reindex() forces a rebuild and returns the new index', async () => {
    const build = vi.fn(async () => ({ generated_at: new Date().toISOString(), docs: [doc] }))
    const ix = createIndexer({ build, load: () => ({ generated_at: new Date().toISOString(), docs: [] }) })
    await ix.reindex()
    expect(build).toHaveBeenCalledTimes(1)
  })
})

describe('createIndexer with local docs', () => {
  const remote = { repo: 'm', path: 'CONTEXT.md', label: 'CONTEXT.md', content: '# A\n\nremote only text\n' }
  const local = { repo: 'm', path: 'CONTEXT.md', label: 'CONTEXT.md', content: '# A\n\nlocal draft text\n', state: 'uncommitted' }
  const fresh = () => ({ generated_at: new Date().toISOString(), docs: [remote] })

  it('searches the local copy instead of the GitHub copy of the same repo', async () => {
    const ix = createIndexer({ build: async () => fresh(), load: fresh, getLocal: async () => ({ repos: new Set(['m']), docs: [local] }) })
    expect((await ix.search('draft')).results[0]).toMatchObject({ repo: 'm', state: 'uncommitted' })
    expect((await ix.search('remote')).results).toEqual([])
  })

  it('still searches GitHub copies of repos with no local clone', async () => {
    const ix = createIndexer({ build: async () => fresh(), load: fresh, getLocal: async () => ({ repos: new Set(['x']), docs: [] }) })
    expect((await ix.search('remote')).results.length).toBe(1)
  })
})

describe('buildDocsIndex keys docs by project id when given one', () => {
  it('uses repo.id for the stored doc, repo.name for GitHub', async () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'docsidx-'))
    try {
      const built = await buildDocsIndex(fakeExec(), [{ name: 'marvin', id: 'marvin-id' }], path.join(dir, 'i.json'))
      expect(built.docs[0].repo).toBe('marvin-id')
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})

describe('createIndexer: local docs are read once, not on every keystroke (2026-10-09: searches took up to 20 s)', () => {
  const idx = { generated_at: new Date().toISOString(), docs: [{ repo: 'r', path: 'a.md', label: 'a.md', content: '# A\nalpha' }] }
  const local = (word) => ({ repos: new Set(['l']), docs: [{ repo: 'l', path: 'b.md', label: 'b.md', content: `# B\n${word}` }] })

  it('answers from memory after the first read', async () => {
    let reads = 0
    const ix = createIndexer({ build: async () => idx, load: () => idx, getLocal: async () => { reads += 1; return local('beta') } })
    await ix.search('beta')
    await ix.search('beta')
    await ix.search('alpha')
    expect(reads).toBe(1)
  })

  it('a docs change refreshes in the background; the next search sees it without waiting', async () => {
    let word = 'beta'
    const ix = createIndexer({ build: async () => idx, load: () => idx, getLocal: async () => local(word) })
    expect((await ix.search('beta')).results.length).toBe(1)
    word = 'gamma'
    ix.localChanged()
    await ix.search('beta')            // served from memory while the refresh runs
    await new Promise((r) => setTimeout(r, 0))
    expect((await ix.search('gamma')).results.length).toBe(1)
  })
})
