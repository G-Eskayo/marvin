// The interactive PDF view's helpers, and the real pdf.js against outline, link and form PDFs (#402).
import { describe, it, expect } from 'vitest'
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs'
import { safeExternalUrl, parsePageInput, clampPage, normalizeOutline, findStatus } from '../src/lib/pdf_nav.js'
import { makePdf } from './fixtures/make_pdf.js'

const open = (opts) => getDocument({ data: new Uint8Array(makePdf(opts)), isEvalSupported: false }).promise

describe('safeExternalUrl: only http, https and mailto ever leave the app', () => {
  it('allows web and mail links', () => {
    expect(safeExternalUrl('https://example.com/a?b=1')).toBe('https://example.com/a?b=1')
    expect(safeExternalUrl('http://example.com')).toBe('http://example.com/')
    expect(safeExternalUrl('mailto:gil@example.com')).toBe('mailto:gil@example.com')
  })
  it('refuses javascript:, file:, data:, custom schemes and junk, however disguised', () => {
    for (const bad of ['javascript:alert(1)', 'JAVASCRIPT:alert(1)', '  javascript:alert(1)', 'java\nscript:alert(1)', 'file:///etc/hosts',
      'FILE:///Users', 'data:text/html,<script>1</script>', 'vbscript:x', 'marvin://do', 'x-apple.systempreferences:', 'smb://host/share',
      'ftp://x', 'tel:123', '//example.com', '/etc/hosts', 'example.com', 'https://', '', null, undefined, 42, {}]) {
      expect(safeExternalUrl(bad), String(bad)).toBeNull()
    }
  })
})

describe('page input', () => {
  it('accepts whole page numbers in range only', () => {
    expect(parsePageInput('400', 500)).toBe(400)
    expect(parsePageInput(' 7 ', 12)).toBe(7)
    for (const bad of ['0', '501', '-3', '2.5', '1e3', 'abc', '', null, '99999999']) expect(parsePageInput(bad, 500), String(bad)).toBeNull()
  })
  it('clamps', () => {
    expect(clampPage(0, 10)).toBe(1)
    expect(clampPage(11, 10)).toBe(10)
    expect(clampPage(NaN, 10)).toBe(1)
    expect(clampPage(3, 0)).toBe(1)
  })
})

describe('find status', () => {
  it('says no matches, one, or many', () => {
    expect(findStatus({ query: '', total: 0 })).toBe('')
    expect(findStatus({ query: 'zz', total: 0 })).toBe('No matches')
    expect(findStatus({ query: 'a', total: 1, current: 1 })).toBe('1 of 1 match')
    expect(findStatus({ query: 'a', total: 240, current: 3 })).toBe('3 of 240 matches')
  })
})

describe('outline with the real pdf.js', () => {
  it('reads nested bookmarks and their destinations', async () => {
    const doc = await open({ pages: 10, outline: [{ title: 'Intro', page: 1 }, { title: 'Results', page: 6, children: [{ title: 'Table 2', page: 8 }] }] })
    const items = normalizeOutline(await doc.getOutline())
    expect(items.map((i) => i.title)).toEqual(['Intro', 'Results'])
    expect(items[1].items[0].title).toBe('Table 2')
    expect(items[1].dest).toBeTruthy()
    expect(await doc.getPageIndex(items[1].items[0].dest[0])).toBe(7)
    await doc.destroy()
  })
  it('a PDF with no outline gives none, and a hostile outline is bounded', async () => {
    const doc = await open({ pages: 2 })
    expect(normalizeOutline(await doc.getOutline())).toEqual([])
    await doc.destroy()
    let deep = []
    for (let i = 0; i < 50; i++) deep = [{ title: `L${i}`, items: deep }]
    const flat = (xs, d = 0) => xs.reduce((m, x) => Math.max(m, flat(x.items, d + 1)), d)
    expect(flat(normalizeOutline(deep))).toBeLessThanOrEqual(13)
    expect(normalizeOutline(Array.from({ length: 5000 }, () => ({ title: 'x' }))).length).toBe(2000)
    expect(normalizeOutline([{ title: 'bad', url: 'javascript:alert(1)' }])[0].url).toBeNull()
  })
})

describe('links with the real pdf.js', () => {
  it('internal links carry a destination; only safe external links survive', async () => {
    const doc = await open({
      pages: 4,
      links: [{ text: 'Go to page 3', page: 3 }, { text: 'Visit example.com', uri: 'https://example.com/' }, { text: 'Bad js', uri: 'javascript:alert(1)' },
        { text: 'Bad file', uri: 'file:///etc/hosts' }, { text: 'JS action', js: 'app.alert(1)' }]
    })
    const annots = (await (await doc.getPage(1)).getAnnotations()).filter((a) => a.subtype === 'Link')
    expect(annots).toHaveLength(5)
    expect(await doc.getPageIndex(annots[0].dest[0])).toBe(2)
    const urls = annots.map((a) => safeExternalUrl(a.url || a.unsafeUrl))
    expect(urls).toEqual([null, 'https://example.com/', null, null, null])
    // pdf.js itself drops the javascript: URL from `url`; we refuse it even from `unsafeUrl`.
    expect(annots[2].url).toBeUndefined()
    await doc.destroy()
  })
})

describe('forms with the real pdf.js', () => {
  it('sees the text field, checkbox and dropdown', async () => {
    const doc = await open({ pages: 1, form: true })
    const fields = await doc.getFieldObjects()
    expect(Object.keys(fields).sort()).toEqual(['agree', 'color', 'name'])
    const widgets = (await (await doc.getPage(1)).getAnnotations()).filter((a) => a.subtype === 'Widget')
    expect(widgets.map((w) => w.fieldType).sort()).toEqual(['Btn', 'Ch', 'Tx'])
    expect(widgets.find((w) => w.fieldType === 'Ch').options.map((o) => o.displayValue)).toEqual(['Red', 'Green', 'Blue'])
    await doc.destroy()
  })
  it('scripting stays off: a JavaScript action is never exposed as something to run', async () => {
    const doc = await open({ pages: 1, links: [{ text: 'JS action', js: 'app.alert(1)' }] })
    const [link] = (await (await doc.getPage(1)).getAnnotations()).filter((a) => a.subtype === 'Link')
    expect(link.url).toBeUndefined()
    expect(safeExternalUrl(link.unsafeUrl)).toBeNull()
    await doc.destroy()
  })
})
