import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import FileView from '../src/components/FileView.jsx'

// #539: with a loader (the Docs tab passes docs.image), a doc's relative image goes through it, never to a raw
// GitHub URL built from the repo root, which broke ../ paths and every private repo.
describe('doc images in the viewer (#539)', () => {
  const file = { kind: 'markdown', content: '# Plan\n\n![shot](../screenshots/a.png)\n', name: 'docs/plans/p.md', path: 'docs/plans/p.md' }
  it('a relative image waits for the loader instead of pointing at GitHub', () => {
    const h = renderToStaticMarkup(<FileView file={file} loadImage={vi.fn()} markdown={{ ctx: { repo: 'acme/private' } }} />)
    expect(h).toContain('aria-label="Loading image"')
    expect(h).not.toContain('raw.githubusercontent.com')
  })
  it('an absolute image URL is left as it is', () => {
    const h = renderToStaticMarkup(<FileView file={{ ...file, content: '![x](https://x.test/a.png)' }} loadImage={vi.fn()} />)
    expect(h).toContain('src="https://x.test/a.png"')
  })
})
