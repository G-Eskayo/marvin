// The `marvin show` window's page (#715), rendered to static HTML. Owner's answers on PR #1029: the look is the
// celestial-navigation tokens (#428) and the "Mock-up look" tag is gone; a web address renders in the window, with
// "Open in browser" in the header and the link card as the fallback.
import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'fs'
import { renderToStaticMarkup } from 'react-dom/server'
import ShowWindow, { ShowBody, HistoryStrip, itemTag } from '../src/components/ShowWindow.jsx'

const api = { current: vi.fn(async () => null), onItem: vi.fn(), onWeb: vi.fn(), read: vi.fn(), image: vi.fn(), openLink: vi.fn(), openInDocs: vi.fn(), setWebBounds: vi.fn() }
const project = { id: 'seal', name: 'Seal Speak' }
const win = (item) => renderToStaticMarkup(<ShowWindow project="seal" api={api} initialItem={item} />)
const body = (item) => renderToStaticMarkup(<ShowBody item={item} api={api} />)
const link = (web) => ({ kind: 'link', url: 'https://example.com/a', label: 'example.com', project, ...(web ? { web } : {}) })

describe('the look', () => {
  it('is the celestial-navigation tokens, and the mock-up tag is gone', () => {
    const html = win({ kind: 'image', label: 'shot.png', project })
    expect(html).toContain('show-root')
    expect(html).toContain('show-hud')
    expect(html).not.toMatch(/Mock-up look|waiting for sign-off|data-mockup-tag/)
    const css = readFileSync(new URL('../src/components/show_window.css', import.meta.url), 'utf8')
    // the token table in docs/design/celestial-navigation/README.md, not a fork of it
    for (const t of ['--bg: #05040A', '--green: #54ff8a', '--amber: #f0b32a', '--line: #7a5a14', '--orange: #ff6a1f', '--red: #ff3b2f', '--dim: #6b551f', '--moon: #cfd6e6']) expect(css).toContain(t)
    expect(css).toMatch(/Saira Condensed/)
    expect(css).toMatch(/Share Tech Mono/)
  })

  it('the header names the project, the item and what kind of thing it is', () => {
    const html = win({ kind: 'markdown', label: 'plan.md', project, pr: { repo: 'G-Eskayo/marvin', number: 934 } })
    expect(html).toContain('Seal Speak')
    expect(html).toContain('plan.md')
    expect(html).toContain('PR #934')
    expect(html).toContain('Open in Docs')
    expect(itemTag({ kind: 'link' })).toBe('Web')
    expect(itemTag({ kind: 'weird' })).toBe('File')
    expect(itemTag(null)).toBeNull()
  })

  it('nothing shown yet: no tag, no buttons', () => {
    const html = win(null)
    expect(html).toContain('Nothing shown yet.')
    expect(html).not.toContain('data-show-tag')
    expect(html).not.toContain('Open in')
  })
})

describe('a web address', () => {
  it('renders in the window (the box the page is drawn into), with Open in browser in the header', () => {
    const html = win(link({ state: 'loading', url: 'https://example.com/a' }))
    expect(html).toContain('data-show-web="loading"')
    expect(html).toContain('Loading https://example.com/a')
    expect(html).toContain('data-show-open-browser')
    expect(html).not.toContain('data-show-link')
    expect(html).toContain('overflow-hidden') // the page scrolls itself; the window doesn't
  })

  it('once loaded, Open in browser still in the header, for the address the page is on now', () => {
    const html = win(link({ state: 'loaded', url: 'https://example.com/b' }))
    expect(html).toContain('data-show-web="loaded"')
    expect(html).toContain('data-show-open-browser')
  })

  it('a page that failed falls back to the link card, with the reason in a red tag', () => {
    const html = body(link({ state: 'failed', url: 'https://example.com/a', reason: 'The page couldn\'t be loaded here (ERR_NAME_NOT_RESOLVED)' }))
    expect(html).toContain('data-show-link')
    expect(html).toContain('data-show-reason')
    expect(html).toContain('ERR_NAME_NOT_RESOLVED')
    expect(html).toContain('Open in browser')
    expect(html).not.toContain('data-show-web')
  })

  it('on a Mac that can\'t draw pages (no web state): the link card, no reason', () => {
    const html = body(link(null))
    expect(html).toContain('data-show-link')
    expect(html).not.toContain('data-show-reason')
    expect(html).toContain('https://example.com/a')
  })

  it('an HTML page is still the sandboxed frame', () => {
    const html = body({ kind: 'html', label: 'index.html', frameUrl: 'marvin-mockup://f1/index.html', project })
    expect(html).toContain('sandbox="allow-scripts"')
    expect(html).not.toContain('allow-same-origin')
  })
})

describe('HistoryStrip', () => {
  const history = [{ id: 'h2', label: 'plan.md', kind: 'markdown', at: 0 }, { id: 'h1', label: 'shot.png', kind: 'image', at: 0 }]
  it('lists the project\'s items newest first and marks the current one', () => {
    const html = renderToStaticMarkup(<HistoryStrip history={history} currentId="h2" onSelect={() => {}} />)
    expect(html.indexOf('plan.md')).toBeLessThan(html.indexOf('shot.png'))
    expect(html).toMatch(/aria-current="true"[^>]*title="plan.md"|title="plan.md"[^>]*aria-current="true"/)
    expect(html).toContain('Doc') // the same kind words as the header tag (itemTag)
    expect(html).toContain('Image')
  })
  it('is hidden with only one item', () => {
    expect(renderToStaticMarkup(<HistoryStrip history={history.slice(0, 1)} currentId="h2" onSelect={() => {}} />)).toBe('')
  })
})
