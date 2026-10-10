import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import StageStrip from '../src/components/StageStrip.jsx'

const parseHtml = (html) => {
  const parser = new DOMParser()
  return parser.parseFromString(html, 'text/html')
}

describe('StageStrip component', () => {
  it('renders all stage segments for empty events', () => {
    const html = renderToStaticMarkup(<StageStrip events={[]} />)
    expect(html).toContain('Claimed')
    expect(html).toContain('Plan')
    expect(html).toContain('Build')
    expect(html).toContain('Verify')
    expect(html).toContain('Merge gate')
    expect(html).toContain('PR')
    expect(html).toContain('Versioning')
    expect(html).toContain('Rebuilding')
    expect(html).toContain('Done')
  })

  it('renders passed stages in green', () => {
    const events = [
      { stage: 'claimed', status: 'passed', timestamp: new Date().toISOString() }
    ]
    const html = renderToStaticMarkup(<StageStrip events={events} />)
    expect(html).toContain('emerald')
  })

  it('renders failed stages in red', () => {
    const events = [
      { stage: 'planning', status: 'failed', detail: 'OUT_OF_ORDER: Merge #208 first', timestamp: new Date().toISOString() }
    ]
    const html = renderToStaticMarkup(<StageStrip events={events} />)
    expect(html).toContain('red')
  })

  it('renders pending stages in gray', () => {
    const html = renderToStaticMarkup(<StageStrip events={[]} />)
    expect(html).toContain('neutral-800')
  })

  it('shows remediation text in title attribute', () => {
    const events = [
      { stage: 'merging', status: 'failed', detail: 'OUT_OF_ORDER: Merge #208 first', timestamp: new Date().toISOString() }
    ]
    const html = renderToStaticMarkup(<StageStrip events={events} />)
    expect(html).toContain('Remediation')
    expect(html).toContain('must merge first')
  })

  it('renders needs-rebase status distinctly for REBASE_CONFLICT', () => {
    const events = [
      { stage: 'gate', status: 'failed', detail: 'REBASE_CONFLICT: after PR #42 merged', timestamp: new Date().toISOString() }
    ]
    const html = renderToStaticMarkup(<StageStrip events={events} />)
    expect(html).toContain('amber')
    expect(html).toContain('rebase')
  })

  it('renders icons for each status', () => {
    const html = renderToStaticMarkup(<StageStrip events={[]} />)
    // Pending stages should have the pending icon
    expect(html).toContain('◌')
  })
})
