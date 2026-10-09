import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import PortfolioHub, { OpenDevSiteButton } from '../src/components/PortfolioHub.jsx'

describe('Portfolio tab "Open dev site" button (marvin#377)', () => {
  it('sits in the Portfolio header, after the dev-site-only note', () => {
    const html = renderToStaticMarkup(<PortfolioHub />)
    const nav = html.slice(html.indexOf('<nav'), html.indexOf('</nav>'))
    expect(nav).toContain('Open dev site')
    expect(nav.indexOf('nothing here touches production')).toBeLessThan(nav.indexOf('Open dev site'))
  })

  it('uses the same button style as its neighbours and shows no message before it is pressed', () => {
    const html = renderToStaticMarkup(<OpenDevSiteButton open={async () => ({ ok: true })} />)
    expect(html).toContain('rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300')
    expect(html).not.toContain('text-red-400')
  })
})
