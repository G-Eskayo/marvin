import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { AddonGate } from '../src/components/AddonGate'
import { AddonNotSetUp } from '../src/components/AddonNotSetUp'

const SpyComponent = ({ setSpy }) => {
  setSpy?.(true)
  return 'RENDERED'
}

describe('AddonGate', () => {
  describe('Item 8: mounting behavior when off', () => {
    it('renders AddonNotSetUp when enabled is false', () => {
      const html = renderToStaticMarkup(
        <AddonGate addon="portfolio" enabled={false} onEnable={() => {}}>
          <SpyComponent />
        </AddonGate>
      )
      expect(html).toContain('Portfolio')
      expect(html).not.toContain('RENDERED')
    })
  })

  describe('Item 9: mounting behavior when on', () => {
    it('renders children when enabled is true, proving gate does not suppress on-state', () => {
      let rendered = false
      const html = renderToStaticMarkup(
        <AddonGate addon="portfolio" enabled={true} onEnable={() => {}}>
          <SpyComponent setSpy={() => { rendered = true }} />
        </AddonGate>
      )
      expect(rendered).toBe(true)
      expect(html).toContain('RENDERED')
    })
  })

  describe('Item 10: loading state', () => {
    it('renders nothing when enabled is null (still loading)', () => {
      const html = renderToStaticMarkup(
        <AddonGate addon="portfolio" enabled={null} onEnable={() => {}}>
          <SpyComponent />
        </AddonGate>
      )
      expect(html).toBe('')
    })

    it('renders nothing when enabled is undefined (still loading)', () => {
      const html = renderToStaticMarkup(
        <AddonGate addon="portfolio" enabled={undefined} onEnable={() => {}}>
          <SpyComponent />
        </AddonGate>
      )
      expect(html).toBe('')
    })
  })

  describe('Item 11: shared component across all add-ons', () => {
    it('AddonNotSetUp renders different names for each addon', () => {
      const portfolio = renderToStaticMarkup(
        <AddonNotSetUp addon="portfolio" onEnable={() => {}} />
      )
      const resumeTailor = renderToStaticMarkup(
        <AddonNotSetUp addon="resume_tailor" onEnable={() => {}} />
      )
      const sealIngest = renderToStaticMarkup(
        <AddonNotSetUp addon="seal_ingest" onEnable={() => {}} />
      )

      expect(portfolio).toContain('Portfolio')
      expect(resumeTailor).toContain('Resume Tailor')
      expect(sealIngest).toContain('Seal Ingest')

      expect(portfolio).not.toContain('Resume Tailor')
      expect(resumeTailor).not.toContain('Portfolio')
      expect(sealIngest).not.toContain('Portfolio')
    })
  })

  describe('Item 12: unknown addon id', () => {
    it('renders unknown add-on message for unknown id', () => {
      const html = renderToStaticMarkup(
        <AddonNotSetUp addon="unknown_addon" onEnable={() => {}} />
      )
      expect(html).toContain('Unknown add-on')
    })
  })
})
