// #611 part 3: text inside PDF deliverables is searchable. Extracted once per PDF content (sha256), cached on disk under a
// size bound, in the background; a search never waits for it. All paths are in a temp dir (temp HOME).
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync, readdirSync, statSync, utimesSync, mkdirSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createPdfText, extractPdfText } from '../electron/main/pdf_text.js'

let root
let cacheDir
beforeEach(() => {
  root = mkdtempSync(path.join(tmpdir(), 'pdftext-'))
  cacheDir = path.join(root, 'home', '.agents', 'var', 'pdf-text')
})
afterEach(() => rmSync(root, { recursive: true, force: true }))

const file = (name, bytes) => {
  const p = path.join(root, name)
  mkdirSync(path.dirname(p), { recursive: true })
  writeFileSync(p, bytes)
  return p
}
const cacheBytes = () => readdirSync(cacheDir).filter((f) => f.endsWith('.txt')).reduce((n, f) => n + statSync(path.join(cacheDir, f)).size, 0)

// A real (tiny) PDF with one line of text, so the pdf.js path is exercised end to end. pdf.js rebuilds the missing xref.
function tinyPdf(text) {
  const stream = `BT /F1 12 Tf 72 720 Td (${text}) Tj ET`
  return Buffer.from(
    [
      '%PDF-1.4',
      '1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj',
      '2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj',
      '3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj',
      `4 0 obj << /Length ${stream.length} >> stream`,
      stream,
      'endstream endobj',
      '5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj',
      'trailer << /Root 1 0 R >>',
      '%%EOF'
    ].join('\n')
  )
}

describe('extractPdfText (pdf.js)', () => {
  it('reads the words on a real PDF page', async () => {
    expect(await extractPdfText(tinyPdf('Parakeet beats Whisper'))).toContain('Parakeet beats Whisper')
  })
  it('throws on bytes that are not a PDF', async () => {
    await expect(extractPdfText(Buffer.from('not a pdf at all'))).rejects.toThrow()
  })
})

describe('createPdfText', () => {
  const make = (o = {}) => createPdfText({ dir: cacheDir, extract: vi.fn(async (b) => `text of ${b.toString('utf8').slice(0, 12)}`), ...o })

  it('a first look returns nothing and queues it; after the background pass the text is there', async () => {
    const p = file('a.pdf', 'pdf-bytes-AAA')
    const onReady = vi.fn()
    const t = make({ onReady })
    expect(t.peek(p)).toBe(null)
    await t.drain()
    expect(t.peek(p)).toBe('text of pdf-bytes-AA')
    expect(onReady).toHaveBeenCalledTimes(1)
  })

  it('extracts once per content: the same bytes at two paths, or a second process, reuse the cache', async () => {
    const a = file('a.pdf', 'same-bytes-123')
    const b = file('dir/b.pdf', 'same-bytes-123')
    const t = make()
    t.peek(a)
    t.peek(b)
    await t.drain()
    expect(t.extract).toHaveBeenCalledTimes(1)
    expect(t.peek(b)).toBe(t.peek(a))
    const again = make() // a restart: keys and text come from disk
    expect(again.peek(a)).toBe('text of same-bytes-1')
    await again.drain()
    expect(again.extract).not.toHaveBeenCalled()
  })

  it('a changed file is extracted again', async () => {
    const p = file('a.pdf', 'version-one!!')
    const t = make()
    t.peek(p)
    await t.drain()
    writeFileSync(p, 'version-two!!!!')
    utimesSync(p, new Date(), new Date(Date.now() + 5000))
    expect(t.peek(p)).toBe(null)
    await t.drain()
    expect(t.peek(p)).toBe('text of version-two!')
  })

  it('an unreadable PDF is cached as empty: no text, and never retried', async () => {
    const p = file('bad.pdf', 'broken')
    const t = make({ extract: vi.fn(async () => { throw new Error('Invalid PDF structure') }) })
    t.peek(p)
    await t.drain()
    expect(t.peek(p)).toBe(null)
    await t.drain()
    expect(t.extract).toHaveBeenCalledTimes(1)
  })

  it('caps the text kept per PDF', async () => {
    const p = file('big.pdf', 'x')
    const t = make({ extract: async () => 'word '.repeat(100_000), maxTextBytes: 1000 })
    t.peek(p)
    await t.drain()
    expect(Buffer.byteLength(t.peek(p))).toBeLessThanOrEqual(1000)
  })

  it('keeps the cache under its size bound, evicting the oldest first', async () => {
    const t = make({ extract: async (b) => `${b.toString()} `.repeat(100), maxBytes: 2500 })
    const paths = []
    for (let i = 0; i < 10; i++) {
      paths.push(file(`p${i}.pdf`, `pdf-number-${i}`))
      t.peek(paths[i])
      await t.drain()
    }
    expect(cacheBytes()).toBeLessThanOrEqual(2500)
    expect(t.peek(paths[9])).toContain('pdf-number-9')
    expect(t.peek(paths[0])).toBe(null)
  })

  it('skips a PDF over the size limit without reading it into pdf.js', async () => {
    const p = file('huge.pdf', Buffer.alloc(2048))
    const t = make({ maxPdfBytes: 1024 })
    expect(t.peek(p)).toBe(null)
    await t.drain()
    expect(t.extract).not.toHaveBeenCalled()
  })

  it('a missing file is nothing, not an error', async () => {
    const t = make()
    expect(t.peek(path.join(root, 'gone.pdf'))).toBe(null)
    await t.drain()
    expect(t.extract).not.toHaveBeenCalled()
  })

  it('one pass at a time: overlapping drains extract each PDF once', async () => {
    const t = make()
    for (let i = 0; i < 5; i++) t.peek(file(`q${i}.pdf`, `distinct-${i}`))
    await Promise.all([t.drain(), t.drain(), t.drain()])
    expect(t.extract).toHaveBeenCalledTimes(5)
  })

  it('a corrupt key file on disk is ignored, not fatal', async () => {
    mkdirSync(cacheDir, { recursive: true })
    writeFileSync(path.join(cacheDir, 'keys.json'), '{not json')
    const p = file('a.pdf', 'pdf-bytes-AAA')
    const t = make()
    t.peek(p)
    await t.drain()
    expect(t.peek(p)).toBe('text of pdf-bytes-AA')
  })
})
