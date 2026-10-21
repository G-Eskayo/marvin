// The real pdf.js (legacy build, runs in Node) against real good, broken, encrypted, empty and huge PDFs (#402).
import { describe, it, expect } from 'vitest'
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs'
import { openPdf, pdfErrorReason, pageScale, viewerScale, pageCountLabel, PDF_RENDER_MAX_PX, PDF_RENDER_MAX_PIXELS } from '../src/lib/pdf_doc.js'
import { makePdf } from './fixtures/make_pdf.js'

describe('openPdf with the real pdf.js', () => {
  it('opens a multi-page PDF and reports its page count and page shape', async () => {
    const r = await openPdf(getDocument, makePdf({ pages: 12 }))
    expect(r.ok).toBe(true)
    expect(r.numPages).toBe(12)
    expect(r.aspect).toBeCloseTo(792 / 612)
    await r.doc.destroy()
  })
  it('a huge page count is lazy: opening touches only page 1', async () => {
    let calls = 0
    const counting = (src) => {
      const task = getDocument(src)
      const promise = task.promise.then((doc) => {
        const get = doc.getPage.bind(doc)
        doc.getPage = (n) => { calls++; return get(n) }
        return doc
      })
      return { promise }
    }
    const r = await openPdf(counting, makePdf({ pages: 500 }))
    expect(r.numPages).toBe(500)
    expect(calls).toBe(1)
    await r.doc.destroy()
  })
  it('a corrupt PDF gets a reason (the card), never a throw', async () => {
    const good = makePdf({ pages: 2 })
    for (const bad of [Buffer.concat([Buffer.from('%PDF-1.4\n'), Buffer.from('garbage '.repeat(50))]), good.subarray(0, 40)]) {
      const r = await openPdf(getDocument, bad)
      expect(r.ok).toBe(false)
      expect(r.reason).toMatch(/damaged|couldn't be read|no pages/i)
    }
  })
  it('an encrypted / password PDF gets the card with a reason saying so', async () => {
    const r = await openPdf(getDocument, makePdf({ pages: 1, encrypt: true }))
    expect(r.ok).toBe(false)
    expect(r.reason).toMatch(/password-protected/i)
  })
  it('a PDF with no pages, and an empty file, get a reason', async () => {
    expect((await openPdf(getDocument, makePdf({ emptyTree: true }))).reason).toMatch(/no pages|damaged|couldn't/i)
    expect((await openPdf(getDocument, Buffer.alloc(0))).reason).toMatch(/empty/i)
    expect((await openPdf(getDocument, null)).ok).toBe(false)
  })
  it('a .pdf that is really text is refused', async () => {
    const r = await openPdf(getDocument, Buffer.from('just some notes, not a pdf'))
    expect(r.ok).toBe(false)
  })
  it('does not detach the caller\'s buffer (pdf.js gets a copy)', async () => {
    const data = new Uint8Array(makePdf({ pages: 1 }))
    const r = await openPdf(getDocument, data)
    expect(data.length).toBeGreaterThan(0)
    await r.doc.destroy()
  })
})

describe('pdfErrorReason', () => {
  it('names password, damage and anything else plainly', () => {
    expect(pdfErrorReason({ name: 'PasswordException' })).toMatch(/password/)
    expect(pdfErrorReason({ name: 'InvalidPDFException' })).toMatch(/damaged/)
    expect(pdfErrorReason(new Error('boom'))).toMatch(/boom/)
    expect(pdfErrorReason(undefined)).toMatch(/unknown/)
  })
})

describe('render scales', () => {
  it('fits a page to the panel width and renders sharp on a Retina display', () => {
    const s = pageScale(612, 792, 900, 2)
    expect(612 * s.css).toBeCloseTo(900)
    expect(s.pixel).toBeCloseTo(s.css * 2)
  })
  it('caps the canvas for huge pages and survives junk', () => {
    const s = pageScale(14400, 14400, 1000, 2)
    expect(14400 * s.pixel).toBeLessThanOrEqual(PDF_RENDER_MAX_PX + 1)
    expect(pageScale(0, 0, 900, 2)).toEqual({ css: 1, pixel: 1 })
    expect(pageScale(612, 792, NaN)).toEqual({ css: 1, pixel: 1 })
  })
  it('renders a page for the viewer at about 4096 px on the long side, within the area cap', () => {
    const v = viewerScale(612, 792)
    expect(792 * v).toBeLessThanOrEqual(PDF_RENDER_MAX_PX + 0.5)
    expect(612 * v * 792 * v).toBeLessThanOrEqual(PDF_RENDER_MAX_PIXELS + 1)
    expect(viewerScale(0, 5)).toBe(1)
  })
  it('labels the page count', () => {
    expect(pageCountLabel(1)).toBe('1 page')
    expect(pageCountLabel(12)).toBe('12 pages')
  })
})
