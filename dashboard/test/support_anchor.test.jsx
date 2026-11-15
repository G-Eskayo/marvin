import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { Thread } from '../src/components/SupportTab.jsx'

describe('Support tab anchor link', () => {
  it('renders with target="_blank" and rel="noreferrer"', () => {
    const thread = {
      request: {
        repo: 'owner/repo',
        number: 42,
        title: 'Test request',
        url: 'https://github.com/owner/repo/issues/42',
        body: 'Test body',
        state: 'needs-you',
        open: true,
        author: 'someone',
        updatedAt: '2026-10-26T00:00:00Z'
      },
      comments: []
    }
    const html = renderToStaticMarkup(
      <Thread thread={thread} role="helper" busy={false} draft="" setDraft={() => {}} check="" setCheck={() => {}} />
    )
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noreferrer"')
    expect(html).toContain('href="https://github.com/owner/repo/issues/42"')
  })
})
