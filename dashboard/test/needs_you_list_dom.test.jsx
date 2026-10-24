import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import NeedsYouList from '../src/components/NeedsYouList.jsx'

describe('NeedsYouList static render tests', () => {
  it('renders with collapsible Needs you section', () => {
    const html = renderToStaticMarkup(
      <NeedsYouList
        boards={[{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }]}
        onOpenTicket={() => {}}
      />
    )
    expect(html).toContain('Needs you')
    expect(html).toContain('data-testid="needs-you"')
  })

  it('renders empty state with section toggle', () => {
    const html = renderToStaticMarkup(
      <NeedsYouList boards={[]} onOpenTicket={() => {}} />
    )
    expect(html).toContain('Needs you')
    expect(html).toContain('Nothing needs you')
  })

  it('renders collapsible toggle button', () => {
    const html = renderToStaticMarkup(
      <NeedsYouList
        boards={[{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }]}
        onOpenTicket={() => {}}
      />
    )
    expect(html).toContain('▾')
  })

  it('includes sort controls in the rendered output', () => {
    const html = renderToStaticMarkup(
      <NeedsYouList
        boards={[{ repo: 'G-Eskayo/marvin', name: 'MARVIN' }]}
        onOpenTicket={() => {}}
      />
    )
    expect(html).toContain('Most unblocks')
    expect(html).toContain('Highest priority')
    expect(html).toContain('Oldest first')
    expect(html).toContain('By project')
  })
})
