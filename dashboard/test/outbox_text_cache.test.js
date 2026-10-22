// #570: the renderer's cache of deliverable text reads (src/lib/outbox_text_cache.js).
import { describe, it, expect, beforeEach } from 'vitest'
import { getCachedFile, putCachedFile, clearCachedFiles, cachedCount, prefetchTextFiles } from '../src/lib/outbox_text_cache.js'

const md = (n, content = '# x') => ({ kind: 'markdown', name: n, path: n, content })
beforeEach(() => clearCachedFiles())

describe('outbox text cache', () => {
  it('keeps text files, never images, PDFs or huge text', () => {
    putCachedFile('a.md', md('a.md'))
    putCachedFile('b.png', { kind: 'image', dataUrl: 'data:' })
    putCachedFile('c.pdf', { kind: 'pdf', data: new Uint8Array(3) })
    putCachedFile('d.md', md('d.md', 'x'.repeat(300 * 1024)))
    expect(getCachedFile('a.md').content).toBe('# x')
    expect(cachedCount()).toBe(1)
  })
  it('is bounded: the least recently used goes first', () => {
    for (let i = 0; i < 45; i++) putCachedFile(`${i}.md`, md(`${i}.md`))
    expect(cachedCount()).toBe(40)
    expect(getCachedFile('0.md')).toBeNull()
    getCachedFile('5.md') // used: survives the next eviction
    putCachedFile('new.md', md('new.md'))
    expect(getCachedFile('5.md')).not.toBeNull()
    expect(getCachedFile('6.md')).toBeNull()
  })
  it('clears on an outbox change, so stale text is never shown', () => {
    putCachedFile('a.md', md('a.md'))
    clearCachedFiles()
    expect(getCachedFile('a.md')).toBeNull()
  })
  it('prefetches only markdown/text files of a folder, at most 8, at idle, and survives a failing read', async () => {
    const reads = []
    const entries = [
      ...Array.from({ length: 10 }, (_, i) => ({ type: 'file', kind: 'markdown', path: `f/${i}.md` })),
      { type: 'file', kind: 'image', path: 'f/a.png' },
      { type: 'dir', path: 'f/sub' }
    ]
    let ran = null
    prefetchTextFiles(entries, async (p) => { reads.push(p); if (p === 'f/1.md') throw new Error('gone'); return md(p) }, (fn) => (ran = fn))
    expect(reads).toEqual([]) // nothing until idle
    ran()
    await new Promise((r) => setTimeout(r, 0))
    expect(reads.length).toBe(8)
    expect(cachedCount()).toBe(7)
  })
})
