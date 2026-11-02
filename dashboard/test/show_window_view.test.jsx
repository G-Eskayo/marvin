// The show window's page (#715): the sandboxed frame, the link card, and the history strip, rendered statically.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ShowBody, HistoryStrip } from '../src/components/ShowWindow.jsx'

const project = { id: 'marvin', name: 'MARVIN' }

describe('ShowBody', () => {
  it('runs HTML in a frame with scripts but no same-origin, pop-ups, forms or top navigation', () => {
    const html = renderToStaticMarkup(<ShowBody item={{ kind: 'html', frameUrl: 'marvin-mockup://f1/index.html', label: 'm', project }} api={{}} />)
    expect(html).toMatch(/<iframe[^>]+sandbox="allow-scripts"/)
    expect(html).toContain('src="marvin-mockup://f1/index.html"')
    expect(html).not.toMatch(/allow-same-origin|allow-popups|allow-top-navigation|allow-forms/)
  })
  it('shows a web address as a link card, never loading it', () => {
    const html = renderToStaticMarkup(<ShowBody item={{ kind: 'link', url: 'https://example.com/', label: 'e', project }} api={{}} />)
    expect(html).toContain('https://example.com/')
    expect(html).toContain('Open in browser')
    expect(html).not.toContain('<iframe')
  })
  it('an error is a card with the reason', () => {
    expect(renderToStaticMarkup(<ShowBody item={{ label: 'x', project }} error="Not found: x" api={{}} />)).toContain('Not found: x')
  })
})

describe('HistoryStrip', () => {
  const history = [{ id: 'h2', label: 'plan.md', kind: 'markdown', at: 0 }, { id: 'h1', label: 'shot.png', kind: 'image', at: 0 }]
  it('lists the project\'s items newest first and marks the current one', () => {
    const html = renderToStaticMarkup(<HistoryStrip history={history} currentId="h2" onSelect={() => {}} />)
    expect(html.indexOf('plan.md')).toBeLessThan(html.indexOf('shot.png'))
    expect(html).toMatch(/aria-current="true"[^>]*title="plan.md"|title="plan.md"[^>]*aria-current="true"/)
    expect(html).toContain('Markdown')
    expect(html).toContain('Image')
  })
  it('is hidden with only one item', () => {
    expect(renderToStaticMarkup(<HistoryStrip history={history.slice(0, 1)} currentId="h2" onSelect={() => {}} />)).toBe('')
  })
})
