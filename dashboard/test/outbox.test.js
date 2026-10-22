// The Files tab's main-process reader (G-Eskayo/marvin#89, #402). Every test runs against a throwaway HOME so the real
// ~/.claude is never read or written (a past test wiped real logs). os.homedir() follows $HOME, and outbox.js resolves
// the root on every call, so pointing HOME at a temp dir is enough.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, symlinkSync, chmodSync, realpathSync } from 'fs'
import { tmpdir, homedir, userInfo } from 'os'
import path from 'path'
import {
  listOutboxTree, readOutboxFile, readOutboxImage, outboxRevealPath, outboxOpenPath, outboxRoot,
  MAX_IMAGE_BYTES, MAX_TEXT_BYTES, MAX_PDF_BYTES
} from '../electron/main/outbox.js'

// A real 1x1 PNG, a real 1x1 JPEG (smallest valid baseline), and an SVG.
const PNG = Buffer.from('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082', 'hex')
const JPEG = Buffer.from('ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9', 'hex')
const SVG = '<?xml version="1.0"?>\n<!-- drawn by hand -->\n<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4"/></svg>'
const PDF = Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n')

let home, prevHome, root
beforeEach(() => {
  prevHome = process.env.HOME
  home = mkdtempSync(path.join(tmpdir(), 'outbox-home-'))
  process.env.HOME = home
  root = path.join(home, '.claude', 'outbox')
  mkdirSync(root, { recursive: true })
})
afterEach(() => {
  process.env.HOME = prevHome
  rmSync(home, { recursive: true, force: true })
})
const put = (rel, data) => {
  mkdirSync(path.dirname(path.join(root, rel)), { recursive: true })
  writeFileSync(path.join(root, rel), data)
}
const dataUrlBytes = (u) => Buffer.from(u.split(',')[1], 'base64')

describe('the sandbox really is a temp HOME', () => {
  it('points the outbox at the temp HOME, not the real one', () => {
    expect(homedir()).toBe(home)
    expect(outboxRoot()).toBe(root)
    expect(outboxRoot()).not.toContain(path.join(userInfo().homedir, '.claude')) // the account's real home, whatever HOME says
  })
})

describe('listOutboxTree', () => {
  it('returns [] when the outbox does not exist', () => {
    rmSync(root, { recursive: true })
    expect(listOutboxTree()).toEqual([])
  })
  it('lists folders first, then files, alphabetically, each file with its kind in plain words', () => {
    put('zeta/a.png', PNG)
    put('alpha/notes.md', '# hi')
    put('b.csv', 'a,b')
    put('a.pdf', PDF)
    put('c.bin', Buffer.from([0, 1, 2]))
    const tree = listOutboxTree()
    expect(tree.map((t) => t.path)).toEqual(['alpha', 'zeta', 'a.pdf', 'b.csv', 'c.bin'])
    expect(tree[0].children).toEqual([{ path: 'alpha/notes.md', type: 'file', kind: 'markdown', label: 'Markdown' }])
    expect(tree[1].children[0]).toMatchObject({ kind: 'image', label: 'Image' })
    expect(tree.slice(2).map((t) => t.label)).toEqual(['PDF', 'Table', 'File'])
  })
})

describe('readOutboxFile: images', () => {
  it('round-trips PNG, JPEG and SVG byte for byte with the right MIME type', () => {
    put('shots/a.png', PNG)
    put('b.jpg', JPEG)
    put('c.svg', SVG)
    const png = readOutboxFile('shots/a.png')
    expect(png).toMatchObject({ kind: 'image', label: 'Image', mime: 'image/png', size: PNG.length, name: 'a.png' })
    expect(png.dataUrl.startsWith('data:image/png;base64,')).toBe(true)
    expect(dataUrlBytes(png.dataUrl).equals(PNG)).toBe(true)
    const jpg = readOutboxFile('b.jpg')
    expect(jpg.mime).toBe('image/jpeg')
    expect(dataUrlBytes(jpg.dataUrl).equals(JPEG)).toBe(true)
    const svg = readOutboxFile('c.svg')
    expect(svg.mime).toBe('image/svg+xml')
    expect(dataUrlBytes(svg.dataUrl).toString('utf8')).toBe(SVG)
    expect(png.content).toBeUndefined()   // never a text dump of the bytes
  })
  it('a text file named .png gets the card, not an image and not its text', () => {
    put('fake.png', 'this is not an image')
    const r = readOutboxFile('fake.png')
    expect(r.kind).toBe('other')
    expect(r.reason).toMatch(/not a valid image/i)
    expect(r.dataUrl).toBeUndefined()
    expect(r.content).toBeUndefined()
  })
  it('a truncated PNG still goes to the renderer as its exact bytes (the viewer falls back to the card if it cannot draw it)', () => {
    const cut = PNG.subarray(0, 30)
    put('cut.png', cut)
    const r = readOutboxFile('cut.png')
    expect(r.kind).toBe('image')
    expect(dataUrlBytes(r.dataUrl).equals(cut)).toBe(true)
  })
  it('an empty .png is the card', () => {
    put('empty.png', '')
    expect(readOutboxFile('empty.png').kind).toBe('other')
  })
  it('an image over the size limit gives the card with its size, never garbage', () => {
    put('huge.png', Buffer.concat([PNG, Buffer.alloc(MAX_IMAGE_BYTES)]))
    const r = readOutboxFile('huge.png')
    expect(r).toMatchObject({ kind: 'other', label: 'Image' })
    expect(r.reason).toMatch(/too large/i)
    expect(r.size).toBeGreaterThan(MAX_IMAGE_BYTES)
    expect(r.dataUrl).toBeUndefined()
    expect(r.content).toBeUndefined()
  })
})

describe('readOutboxFile: text kinds', () => {
  it('reads markdown, notebooks, CSV, HTML, code and text as text with their kind', () => {
    const files = { 'a.md': 'markdown', 'b.ipynb': 'notebook', 'c.csv': 'table', 'd.tsv': 'table', 'e.html': 'html', 'f.py': 'code', 'g.txt': 'text' }
    for (const [name, kind] of Object.entries(files)) {
      put(name, `content of ${name}`)
      expect(readOutboxFile(name), name).toMatchObject({ kind, content: `content of ${name}` })
    }
  })
  it('valid JSON is json; invalid JSON falls back to text, still labelled JSON', () => {
    put('ok.json', '{"a":[1,2]}')
    put('bad.json', '{nope')
    expect(readOutboxFile('ok.json').kind).toBe('json')
    expect(readOutboxFile('bad.json')).toMatchObject({ kind: 'text', label: 'JSON', content: '{nope' })
  })
  it('a CSV with quoted commas and an empty CSV both come through untouched', () => {
    put('q.csv', 'a,b\n"x, y",z\n')
    put('empty.csv', '')
    expect(readOutboxFile('q.csv').content).toBe('a,b\n"x, y",z\n')
    expect(readOutboxFile('empty.csv')).toMatchObject({ kind: 'table', content: '' })
  })
  it('keeps unicode and odd file names', () => {
    put('файл_🎉.txt', 'unicode ✓')
    expect(readOutboxFile('файл_🎉.txt')).toMatchObject({ kind: 'text', content: 'unicode ✓', name: 'файл_🎉.txt' })
  })
  it('a binary file with a text extension, or an unknown binary, gets the card, never raw bytes', () => {
    put('bin.txt', Buffer.from([0x50, 0, 0x4b, 3, 4]))
    put('x.zip', Buffer.from([0x50, 0x4b, 3, 4, 0]))
    for (const n of ['bin.txt', 'x.zip']) {
      const r = readOutboxFile(n)
      expect(r.kind, n).toBe('other')
      expect(r.content).toBeUndefined()
    }
  })
  it('an unknown extension that is plain text shows as text', () => {
    put('Makefile', 'all:\n\techo hi\n')
    expect(readOutboxFile('Makefile')).toMatchObject({ kind: 'text', label: 'File' })
  })
  it('text over the size limit gets the card, not a sliced dump', () => {
    put('big.log', 'x'.repeat(MAX_TEXT_BYTES + 1))
    const r = readOutboxFile('big.log')
    expect(r.kind).toBe('other')
    expect(r.reason).toMatch(/too large/i)
    expect(r.content).toBeUndefined()
  })
})

describe('readOutboxFile: PDFs', () => {
  it('a real PDF comes back as its exact bytes for the renderer\'s pdf.js view', () => {
    put('docs/r p.pdf', PDF)
    const r = readOutboxFile('docs/r p.pdf')
    expect(r).toMatchObject({ kind: 'pdf', label: 'PDF', size: PDF.length })
    expect(Buffer.from(r.data).equals(PDF)).toBe(true)
    expect(r.content).toBeUndefined()
  })
  it('a .pdf that is really text, or empty, gets the card and no bytes', () => {
    put('fake.pdf', '<html>hi</html>')
    put('empty.pdf', '')
    for (const n of ['fake.pdf', 'empty.pdf']) {
      const r = readOutboxFile(n)
      expect(r.kind, n).toBe('other')
      expect(r.data).toBeUndefined()
    }
  })
  it('a PDF over the size limit gets the card without being read', () => {
    put('huge.pdf', Buffer.concat([PDF, Buffer.alloc(MAX_PDF_BYTES)]))
    const r = readOutboxFile('huge.pdf')
    expect(r.kind).toBe('other')
    expect(r.reason).toMatch(/too large/i)
    expect(r.data).toBeUndefined()
  })
  it('Open in Preview only opens PDFs inside the outbox', () => {
    put('a.pdf', PDF)
    put('run.command', '#!/bin/sh\necho hi')
    writeFileSync(path.join(home, 'secret.pdf'), PDF)
    expect(outboxOpenPath('a.pdf')).toBe(path.join(root, 'a.pdf'))
    expect(() => outboxOpenPath('run.command')).toThrow(/only pdfs/i)
    expect(() => outboxOpenPath('../secret.pdf')).toThrow()
    expect(() => outboxOpenPath(path.join(home, 'secret.pdf'))).toThrow()
    expect(() => outboxOpenPath('missing.pdf')).toThrow()
  })
})

describe('readOutboxFile: refusals and failures', () => {
  it('rejects traversal, absolute paths and non-strings for every kind', () => {
    writeFileSync(path.join(home, '.claude', 'secret.png'), PNG)
    writeFileSync(path.join(home, '.claude', 'secret.md'), '# secret')
    for (const bad of ['../secret.png', '../secret.md', 'a/../../secret.md', '..', path.join(home, '.claude', 'secret.md'), 42, null, undefined]) {
      expect(() => readOutboxFile(bad), String(bad)).toThrow()
    }
  })
  it('rejects a symlink that points outside the outbox', () => {
    writeFileSync(path.join(home, 'outside.png'), PNG)
    symlinkSync(path.join(home, 'outside.png'), path.join(root, 'link.png'))
    expect(() => readOutboxFile('link.png')).toThrow()
  })
  it('a missing file throws a plain "not found"', () => {
    expect(() => readOutboxFile('nope.png')).toThrow(/not found/i)
  })
  it('a folder is not a file', () => {
    mkdirSync(path.join(root, 'dir.png'))
    expect(() => readOutboxFile('dir.png')).toThrow(/not a regular file/i)
  })
  it('an unreadable file gets the card saying it cannot be read', () => {
    put('locked.md', 'secret')
    chmodSync(path.join(root, 'locked.md'), 0o000)
    try {
      const r = readOutboxFile('locked.md')
      if (process.getuid?.() === 0) return   // root reads anything
      expect(r.kind).toBe('other')
      expect(r.reason).toMatch(/can't be read/i)
      expect(r.content).toBeUndefined()
    } finally {
      chmodSync(path.join(root, 'locked.md'), 0o600)
    }
  })
})

describe('readOutboxImage: images embedded in outbox markdown', () => {
  it('resolves a relative image against the markdown file\'s own folder', () => {
    put('report/notes.md', '![x](shots/a.png)')
    put('report/shots/a.png', PNG)
    put('report/b.png', PNG)
    for (const src of ['shots/a.png', './shots/a.png', 'b.png', 'shots/a.png?raw=1', 'shots/a.png#frag']) {
      const r = readOutboxImage('report/notes.md', src)
      expect(r.ok, src).toBe(true)
      expect(dataUrlBytes(r.dataUrl).equals(PNG)).toBe(true)
    }
  })
  it('decodes URL-escaped names (spaces written as %20)', () => {
    put('r/notes.md', '')
    put('r/my shot.png', PNG)
    expect(readOutboxImage('r/notes.md', 'my%20shot.png').ok).toBe(true)
  })
  it('allows ../ that stays inside the outbox, and refuses any that escapes it', () => {
    put('a/b/notes.md', '')
    put('a/up.png', PNG)
    writeFileSync(path.join(home, '.claude', 'secret.png'), PNG)
    writeFileSync(path.join(home, 'secret.png'), PNG)
    expect(readOutboxImage('a/b/notes.md', '../up.png').ok).toBe(true)
    for (const src of ['../../../secret.png', '../../../../secret.png', '..%2F..%2F..%2Fsecret.png', '/etc/hosts', path.join(home, 'secret.png'), 'file:///etc/hosts']) {
      const r = readOutboxImage('a/b/notes.md', src)
      expect(r.ok, src).toBe(false)
      expect(r.dataUrl).toBeUndefined()
    }
  })
  it('refuses a markdown path that itself escapes, and non-images', () => {
    put('notes.md', '')
    put('plain.txt', 'hello')
    put('fake.png', 'hello')
    expect(readOutboxImage('../x.md', 'a.png').ok).toBe(false)
    expect(readOutboxImage('notes.md', 'plain.txt').ok).toBe(false)
    expect(readOutboxImage('notes.md', 'fake.png').ok).toBe(false)
    expect(readOutboxImage('notes.md', 'missing.png').ok).toBe(false)
    expect(readOutboxImage('notes.md', '').ok).toBe(false)
    expect(readOutboxImage('notes.md', null).ok).toBe(false)
  })
  it('leaves remote and data: images to the page (not read from disk)', () => {
    put('notes.md', '')
    expect(readOutboxImage('notes.md', 'https://example.com/a.png')).toMatchObject({ ok: false })
    expect(readOutboxImage('notes.md', 'data:image/png;base64,AA')).toMatchObject({ ok: false })
  })
})

describe('outboxRevealPath', () => {
  it('gives the real path of an outbox file for Reveal in Finder, and refuses anything outside', () => {
    put('a/b.zip', 'x')
    expect(outboxRevealPath('a/b.zip')).toBe(path.join(root, 'a/b.zip'))
    expect(() => outboxRevealPath('../secret')).toThrow()
    expect(() => outboxRevealPath('missing.zip')).toThrow()
  })
  it('works with the real (resolved) temp path too', () => {
    put('c.txt', 'x')
    expect(realpathSync(outboxRevealPath('c.txt'))).toBe(realpathSync(path.join(root, 'c.txt')))
  })
})
