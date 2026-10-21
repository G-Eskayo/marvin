// FileView picks the renderer for each kind; ImageViewer is the one full-size viewer (G-Eskayo/marvin#402).
// Rendered to static HTML (the suite has no DOM); clicks and zoom are exercised in the real app by the evidence
// script (scripts/files_viewer_evidence.mjs) and the zoom maths in image_zoom.test.js.
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import FileView from '../src/components/FileView.jsx'
import ImageViewer from '../src/components/ImageViewer.jsx'
import Markdown from '../src/components/Markdown.jsx'
import { viewerItems } from '../src/components/PrImages.jsx'
import { TABLE_ROW_LIMIT } from '../src/lib/file_view.js'

const PNG_URL = 'data:image/png;base64,iVBORw0KGgo='
const render = (file, props = {}) => renderToStaticMarkup(<FileView file={file} {...props} />)

describe('FileView', () => {
  it('shows an image as the image, scaled to the panel and never wider than itself, and clickable to zoom', () => {
    const html = render({ kind: 'image', name: 'a.png', dataUrl: PNG_URL, label: 'Image', size: 10 })
    expect(html).toContain(`src="${PNG_URL}"`)
    expect(html).toContain('max-w-full')
    expect(html).toContain('cursor-zoom-in')
    expect(html).not.toContain('<pre')
  })

  it('renders markdown; a relative image waits for its bytes from main instead of a broken path', () => {
    const loadImage = vi.fn(() => new Promise(() => {}))
    const html = render({ kind: 'markdown', name: 'n.md', content: '# Hi\n\n![shot](shots/x.png)\n\n![web](https://example.com/y.png)' }, { loadImage })
    expect(html).toContain('<h1')
    expect(html).toContain('aria-label="Loading image"')
    expect(html).not.toContain('src="shots/x.png"')
    expect(html).toContain('src="https://example.com/y.png"')   // remote images are left to the page
  })

  it('in the Docs tab (no loader) keeps resolving repo images on GitHub, and they open in the viewer', () => {
    const html = render({ kind: 'markdown', name: 'README.md', content: '![a](docs/a.png)' }, { markdown: { ctx: { repo: 'G-Eskayo/marvin' } } })
    expect(html).toContain('src="https://raw.githubusercontent.com/G-Eskayo/marvin/HEAD/docs/a.png"')
    expect(html).toContain('cursor-zoom-in')
  })

  it('renders a notebook through the Docs tab\'s converter', () => {
    const nb = JSON.stringify({ cells: [{ cell_type: 'markdown', source: ['# From a notebook'] }], metadata: {} })
    expect(render({ kind: 'notebook', name: 'a.ipynb', content: nb })).toContain('From a notebook</h1>')
  })

  it('pretty-prints JSON and shows code/text monospace, escaped', () => {
    expect(render({ kind: 'json', name: 'a.json', content: '{"a":[1]}' })).toContain('{\n  &quot;a&quot;: [\n    1\n  ]\n}')
    const code = render({ kind: 'code', name: 'a.js', content: '<script>alert(1)</script>' })
    expect(code).toContain('<pre')
    expect(code).toContain('&lt;script&gt;')
    expect(code).not.toContain('<script>')
  })

  it('shows CSV as a table, keeping quoted commas in one cell; TSV splits on tabs', () => {
    const html = render({ kind: 'table', name: 'a.csv', content: 'name,note\n"Smith, J",ok\n' })
    expect(html).toContain('<table')
    expect(html).toContain('<th class="border border-neutral-700 bg-neutral-900 px-2 py-1 text-left font-semibold text-neutral-100">name</th>')
    expect(html).toContain('>Smith, J</td>')
    expect(html).toContain('1 row.')
    expect(render({ kind: 'table', name: 'a.tsv', content: 'a\tb,c\n1\t2' })).toContain('>b,c</th>')
  })

  it('an empty CSV says so; a huge one renders only the first rows and says how many there are', () => {
    expect(render({ kind: 'table', name: 'e.csv', content: '' })).toContain('This table is empty.')
    const big = ['h', ...Array.from({ length: TABLE_ROW_LIMIT + 50 }, (_, i) => String(i))].join('\n')
    const html = render({ kind: 'table', name: 'big.csv', content: big })
    expect(html.match(/<tr>/g)).toHaveLength(TABLE_ROW_LIMIT + 1)
    expect(html).toContain(`Showing the first ${TABLE_ROW_LIMIT} of ${TABLE_ROW_LIMIT + 50} rows.`)
  })

  it('renders a PDF with its own pdf.js view (no Chromium viewer iframe), starting with a loading line', () => {
    const html = render({ kind: 'pdf', name: 'r.pdf', data: new Uint8Array([37, 80, 68, 70, 45]) })
    expect(html).toContain('Loading PDF…')
    expect(html).not.toContain('<iframe')
    expect(html).not.toContain('outbox://')
  })

  it('renders HTML in an empty sandbox (no scripts, forms, popups) behind a no-network CSP', () => {
    const html = render({ kind: 'html', name: 'p.html', content: '<script>alert(1)</script><img src="https://evil.example/x.png">' })
    expect(html).toMatch(/<iframe[^>]* sandbox=""/)
    expect(html).not.toContain('allow-scripts')
    expect(html).not.toContain('allow-same-origin')
    expect(html).toContain('srcDoc=') // React writes the attribute as srcDoc in static markup
    expect(html).toContain('default-src &#x27;none&#x27;')
  })

  it('anything else is a card with the name, kind, size, reason and Reveal in Finder, never raw bytes', () => {
    const html = render({ kind: 'other', name: 'x.zip', label: 'File', size: 2048, reason: 'No preview for this kind of file.' }, { onReveal: () => {} })
    expect(html).toContain('x.zip')
    expect(html).toContain('File · 2 KB')
    expect(html).toContain('No preview for this kind of file.')
    expect(html).toContain('Reveal in Finder')
    expect(html).not.toContain('<pre')
  })

  it('renders nothing for no file', () => {
    expect(render(null)).toBe('')
  })
})

describe('Markdown images', () => {
  it('without an opener they are plain images (no zoom cursor)', () => {
    const html = renderToStaticMarkup(<Markdown content={'![a](https://x/y.png)'} />)
    expect(html).toContain('src="https://x/y.png"')
    expect(html).not.toContain('cursor-zoom-in')
  })
})

describe('ImageViewer', () => {
  const items = [
    { src: PNG_URL, alt: 'one', caption: 'First caption', group: 'Main screen' },
    { status: 'loading' },
    { status: 'error', reason: 'HTTP 404' }
  ]
  const view = (props) => renderToStaticMarkup(<ImageViewer items={items} onClose={() => {}} onIndex={() => {}} {...props} />)

  it('opts out of the title bar\'s window-drag area so ✕ and clicks over the header reach it', () => {
    expect(view({ index: 0 })).toContain('-webkit-app-region:no-drag')
  })

  it('has ✕ Close, the zoom controls, the position and the caption, in the existing overlay look', () => {
    const html = view({ index: 0 })
    for (const label of ['aria-label="Close"', 'aria-label="Zoom in"', 'aria-label="Zoom out"', 'aria-label="Fit"', 'aria-label="Actual size"']) expect(html).toContain(label)
    expect(html).toContain('Main screen · 1 of 3')
    expect(html).toContain('First caption')
    expect(html).toContain('bg-black/95')
    expect(html).toContain('aria-label="Previous"')
  })

  it('shows loading and errors per item, without zoom controls', () => {
    expect(view({ index: 1 })).toContain('Loading…')
    const err = view({ index: 2 })
    expect(err).toContain('couldn&#x27;t load: HTTP 404')
    expect(err).not.toContain('aria-label="Zoom in"')
  })

  it('a recording plays with controls and has no zoom', () => {
    const html = renderToStaticMarkup(<ImageViewer items={[{ src: 'prmedia://media/x', kind: 'video', status: 'ok' }]} onClose={() => {}} />)
    expect(html).toContain('<video')
    expect(html).not.toContain('aria-label="Zoom in"')
    expect(html).not.toContain('aria-label="Previous"')   // one item: no arrows
  })

  it('survives an out-of-range index, no items and junk', () => {
    expect(() => view({ index: 99 })).not.toThrow()
    expect(() => renderToStaticMarkup(<ImageViewer items={[]} onClose={() => {}} />)).not.toThrow()
    expect(() => renderToStaticMarkup(<ImageViewer items={null} />)).not.toThrow()
  })
})

describe('PrImages feeds the shared viewer', () => {
  it('maps loaded state to viewer items, keeping group, caption and video kind', () => {
    const images = [{ url: 'u1', alt: 'a', caption: 'c', group: 'g' }, { url: 'u2' }, { url: 'u3' }]
    const loaded = { u1: { status: 'ok', kind: 'image', src: PNG_URL }, u2: { status: 'ok', kind: 'video', src: 'prmedia://media/x' }, u3: { status: 'error', reason: 'boom' } }
    expect(viewerItems(images, loaded)).toEqual([
      { src: PNG_URL, kind: 'image', status: 'ok', reason: undefined, alt: 'a', caption: 'c', group: 'g' },
      { src: 'prmedia://media/x', kind: 'video', status: 'ok', reason: undefined, alt: undefined, caption: undefined, group: undefined },
      { src: undefined, kind: undefined, status: 'error', reason: 'boom', alt: undefined, caption: undefined, group: undefined }
    ])
    expect(viewerItems(null, {})).toEqual([])
  })
})
