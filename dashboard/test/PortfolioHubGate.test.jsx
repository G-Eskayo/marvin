import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import PortfolioHubGate from '../src/components/PortfolioHubGate.jsx'

describe('PortfolioHubGate', () => {
  it('renders loading state initially', () => {
    vi.stubGlobal('window', {
      api: {
        instance: {
          features: vi.fn().mockResolvedValue({ portfolio: true })
        }
      }
    })
    const html = renderToStaticMarkup(<PortfolioHubGate />)
    expect(html).toContain('Loading')
  })
})
