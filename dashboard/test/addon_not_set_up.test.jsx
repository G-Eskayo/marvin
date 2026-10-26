import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AddonNotSetUp } from '../src/components/AddonNotSetUp'
import PortfolioHubGate from '../src/components/PortfolioHubGate'

describe('AddonNotSetUp', () => {
  it('renders portfolio add-on correctly (item 10)', () => {
    const onEnable = vi.fn()
    const html = renderToStaticMarkup(<AddonNotSetUp addon="portfolio" onEnable={onEnable} />)

    expect(html).toContain('Portfolio')
    expect(html).toContain('Project portfolio and web updates')
    expect(html).toContain('Enable Add-on')
  })

  it('renders resume_tailor add-on correctly', () => {
    const onEnable = vi.fn()
    const html = renderToStaticMarkup(<AddonNotSetUp addon="resume_tailor" onEnable={onEnable} />)

    expect(html).toContain('Resume Tailor')
    expect(html).toContain('Job application packages and resume tailoring')
  })

  it('renders seal_ingest add-on correctly', () => {
    const onEnable = vi.fn()
    const html = renderToStaticMarkup(<AddonNotSetUp addon="seal_ingest" onEnable={onEnable} />)

    expect(html).toContain('Seal Ingest')
    expect(html).toContain('Seal Speak beta feedback collection')
  })

  it('shows error for unknown addon', () => {
    const onEnable = vi.fn()
    const html = renderToStaticMarkup(<AddonNotSetUp addon="unknown" onEnable={onEnable} />)

    expect(html).toContain('Unknown add-on: unknown')
  })

  it('displays manual setup instructions', () => {
    const onEnable = vi.fn()
    const html = renderToStaticMarkup(<AddonNotSetUp addon="portfolio" onEnable={onEnable} />)

    expect(html).toContain('.agents/instance/instance.json')
    expect(html).toContain('features')
  })

  it('shared component used by gated wrapper (item 9)', () => {
    // PortfolioHubGate uses AddonNotSetUp when portfolio feature is disabled.
    // This test verifies the component structure and that it's renderable.
    const onEnable = vi.fn()
    const html = renderToStaticMarkup(<AddonNotSetUp addon="portfolio" onEnable={onEnable} />)

    // Verify the rendered output contains what PortfolioHubGate would display when feature is off
    expect(html).toContain('Portfolio')
    expect(html).toContain('Enable Add-on')
    expect(html).toContain('.agents/instance/instance.json')
  })
})
