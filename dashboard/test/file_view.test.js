import { describe, it, expect } from 'vitest'
import { fileKind, formatSize } from '../src/lib/file_kinds.js'
import { parseDelimited, sandboxedHtml, TABLE_ROW_LIMIT } from '../src/lib/file_view.js'

describe('fileKind: each file\'s kind in plain words, from its name alone', () => {
  it('names the kinds the Files tab knows', () => {
    const cases = {
      'a.png': ['image', 'Image'], 'b.JPG': ['image', 'Image'], 'c.jpeg': ['image', 'Image'], 'd.gif': ['image', 'Image'],
      'e.webp': ['image', 'Image'], 'f.svg': ['image', 'Image'], 'g.pdf': ['pdf', 'PDF'], 'h.md': ['markdown', 'Markdown'],
      'i.markdown': ['markdown', 'Markdown'], 'j.ipynb': ['notebook', 'Notebook'], 'k.json': ['json', 'JSON'],
      'l.csv': ['table', 'Table'], 'm.tsv': ['table', 'Table'], 'n.html': ['html', 'Web page'], 'o.htm': ['html', 'Web page'],
      'p.py': ['code', 'Code'], 'q.jsx': ['code', 'Code'], 'r.yml': ['code', 'Code'], 's.txt': ['text', 'Text'], 't.log': ['text', 'Text']
    }
    for (const [name, [kind, label]] of Object.entries(cases)) expect(fileKind(name), name).toEqual({ kind, label })
  })
  it('calls anything unknown a File, including no extension, dotfiles and odd input', () => {
    for (const name of ['archive.zip', 'Makefile', '.env', 'weird.', '', null, undefined, 42]) expect(fileKind(name).label).toBe('File')
  })
  it('uses only the last extension, so a disguised name does not fool it', () => {
    expect(fileKind('shot.png.txt').kind).toBe('text')
    expect(fileKind('dir.with.dots/report.pdf').kind).toBe('pdf')
  })
})

describe('formatSize', () => {
  it('prints human sizes and tolerates missing input', () => {
    expect(formatSize(0)).toBe('0 B')
    expect(formatSize(1536)).toBe('1.5 KB')
    expect(formatSize(5 * 1024 * 1024)).toBe('5 MB')
    expect(formatSize(null)).toBe('')
    expect(formatSize(NaN)).toBe('')
  })
})

describe('parseDelimited: CSV/TSV to rows', () => {
  it('keeps commas, quotes and newlines that are inside quotes', () => {
    const rows = parseDelimited('name,note\n"Smith, J","said ""hi""\nthen left"\nplain,x\n', ',')
    expect(rows).toEqual([['name', 'note'], ['Smith, J', 'said "hi"\nthen left'], ['plain', 'x']])
  })
  it('handles CRLF, a BOM, a missing final newline and ragged rows (padded to the widest)', () => {
    expect(parseDelimited('﻿a,b,c\r\n1,2\r\n3,4,5,6', ',')).toEqual([['a', 'b', 'c', ''], ['1', '2', '', ''], ['3', '4', '5', '6']])
  })
  it('splits TSV on tabs and leaves commas alone', () => {
    expect(parseDelimited('a\tb,c\n1\t2', '\t')).toEqual([['a', 'b,c'], ['1', '2']])
  })
  it('returns no rows for an empty or whitespace-only file, and never throws on junk', () => {
    expect(parseDelimited('', ',')).toEqual([])
    expect(parseDelimited('\n\n', ',')).toEqual([])
    expect(parseDelimited(null, ',')).toEqual([])
    expect(() => parseDelimited('"unclosed,quote\nmore', ',')).not.toThrow()
    expect(parseDelimited('"unclosed,quote', ',')).toEqual([['unclosed,quote']])
  })
  it('keeps empty cells and empty quoted cells', () => {
    expect(parseDelimited('a,,""\n,,', ',')).toEqual([['a', '', ''], ['', '', '']])
  })
  it('has a row limit for rendering big tables', () => {
    expect(TABLE_ROW_LIMIT).toBeGreaterThan(100)
  })
})

describe('sandboxedHtml: an HTML file rendered with no scripts and no network', () => {
  const csp = (doc) => doc.match(/http-equiv="Content-Security-Policy" content="([^"]+)"/)[1]
  it('puts a deny-everything CSP before the page, allowing only inline styles and data: images/fonts', () => {
    const doc = sandboxedHtml('<html><head><link rel="stylesheet" href="https://evil.example/x.css"></head><body>hi</body></html>')
    expect(doc.indexOf('Content-Security-Policy')).toBeLessThan(doc.indexOf('<html>'))
    const policy = csp(doc)
    expect(policy).toContain("default-src 'none'")
    expect(policy).not.toMatch(/script-src|https?:|\*/)
    expect(policy).toContain('img-src data:')
  })
  it('removes meta refresh (a redirect that would load a remote page) and any CSP the page brings', () => {
    const doc = sandboxedHtml('<META HTTP-EQUIV="refresh" content="0;url=https://evil.example"><meta http-equiv=\'Content-Security-Policy\' content="default-src *">x')
    expect(doc).not.toMatch(/refresh/i)
    expect(doc).not.toContain('default-src *')
    expect(doc.match(/Content-Security-Policy/g)).toHaveLength(1)
  })
  it('tolerates empty and non-string input', () => {
    expect(sandboxedHtml('')).toContain("default-src 'none'")
    expect(sandboxedHtml(null)).toContain("default-src 'none'")
  })
})
