import { describe, it, expect, beforeAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// marvin#771: on a vertical monitor the tab bar ran off the right edge and wide content pushed the page sideways.
// jsdom has no layout, so these pin the classes that make each piece wrap or scroll in its own box; the real check is
// opening every tab in the built app at 1080 and 760 px and measuring overflow (0 px on every tab, see the PR).
let App, PortfolioHub, EvidenceTable
beforeAll(async () => {
  globalThis.window = globalThis.window || globalThis
  window.api = new Proxy({}, { get: () => new Proxy(() => Promise.resolve({}), { get: () => () => Promise.resolve({}) }) })
  App = (await import('../src/App.jsx')).default
  PortfolioHub = (await import('../src/components/PortfolioHub.jsx')).default
  EvidenceTable = (await import('../src/components/MrReview.jsx')).EvidenceTable
})
const classOf = (html, tag) => (html.match(new RegExp(`<${tag}[^>]*class="([^"]*)"`)) || [])[1]?.split(' ') || []

describe('the dashboard fits the window (#771)', () => {
  it('header and tab bar wrap onto another line; a tab label never breaks mid-word', () => {
    const h = renderToStaticMarkup(<App />)
    expect(classOf(h, 'header')).toContain('flex-wrap')
    expect(classOf(h, 'nav')).toContain('flex-wrap')
    const tabs = [...h.matchAll(/<nav[^>]*>(.*?)<\/nav>/gs)][0][1].match(/<button[^>]*class="([^"]*)"/g)
    expect(tabs.length).toBeGreaterThanOrEqual(6)
    for (const t of tabs) expect(t).toContain('whitespace-nowrap')
  })

  it('Portfolio sub-tabs wrap rather than squeezing labels', () => {
    const h = renderToStaticMarkup(<PortfolioHub />)
    expect(classOf(h, 'nav')).toContain('flex-wrap')
    expect(h).toMatch(/<button[^>]*whitespace-nowrap[^>]*>Guide &amp; rules/)
  })

  it('a wide table scrolls inside its own box, not the page', () => {
    const h = renderToStaticMarkup(<EvidenceTable metrics={[{ metric: 'a', before: 1, after: 2, threshold: 3, pass: true }]} />)
    expect(h).toMatch(/^<div class="overflow-x-auto"><table/)
  })
})
