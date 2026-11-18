import { describe, it, expect } from 'vitest'
import { resolveDocLink } from '../src/lib/doc_links.js'

describe('resolveDocLink', () => {
  it('ignores absolute URLs', () => {
    expect(resolveDocLink('https://example.com', 'docs/README.md')).toBeNull()
    expect(resolveDocLink('http://example.com', 'docs/README.md')).toBeNull()
  })

  it('ignores protocol-relative URLs', () => {
    expect(resolveDocLink('//example.com', 'docs/README.md')).toBeNull()
  })

  it('ignores data: URIs', () => {
    expect(resolveDocLink('data:text/html,<h1>hi</h1>', 'docs/README.md')).toBeNull()
  })

  it('ignores fragments on absolute URLs', () => {
    expect(resolveDocLink('https://example.com#section', 'docs/README.md')).toBeNull()
  })

  it('resolves a relative link in same directory: docs/plan.md from docs/README.md', () => {
    const r = resolveDocLink('plan.md', 'docs/README.md')
    expect(r).toEqual({ type: 'doc', anchor: null, path: 'docs/plan.md' })
  })

  it('resolves .. going up one level: ../CONTEXT.md from docs/README.md', () => {
    const r = resolveDocLink('../CONTEXT.md', 'docs/README.md')
    expect(r).toEqual({ type: 'doc', anchor: null, path: 'CONTEXT.md' })
  })

  it('resolves .. going up two levels: ../../docs/README.md from docs/plans/README.md', () => {
    const r = resolveDocLink('../../CONTEXT.md', 'docs/plans/README.md')
    expect(r).toEqual({ type: 'doc', anchor: null, path: 'CONTEXT.md' })
  })

  it('separates a relative link with an anchor: plan.md#section from docs/README.md', () => {
    const r = resolveDocLink('plan.md#my-section', 'docs/README.md')
    expect(r).toEqual({ type: 'doc', anchor: 'my-section', path: 'docs/plan.md' })
  })

  it('handles anchors on parent-dir links: ../CONTEXT.md#design', () => {
    const r = resolveDocLink('../CONTEXT.md#design', 'docs/README.md')
    expect(r).toEqual({ type: 'doc', anchor: 'design', path: 'CONTEXT.md' })
  })

  it('returns null if relative resolution goes outside the repo root', () => {
    expect(resolveDocLink('../../../../../../etc/passwd', 'docs/README.md')).toBeNull()
  })

  it('resolves anchor-only fragments as same-doc links', () => {
    expect(resolveDocLink('#section', 'docs/README.md')).toEqual({ type: 'doc', anchor: 'section', path: 'docs/README.md' })
    expect(resolveDocLink('#my-heading', 'CONTEXT.md')).toEqual({ type: 'doc', anchor: 'my-heading', path: 'CONTEXT.md' })
  })

  it('ignores empty hrefs', () => {
    expect(resolveDocLink('', 'docs/README.md')).toBeNull()
    expect(resolveDocLink(null, 'docs/README.md')).toBeNull()
  })

  it('resolves leading / to repo root: /CONTEXT.md from docs/adr/0032.md', () => {
    const r = resolveDocLink('/CONTEXT.md', 'docs/adr/0032.md')
    expect(r).toEqual({ type: 'doc', anchor: null, path: 'CONTEXT.md' })
  })

  it('resolves leading / with anchor: /docs/plan.md#section from CONTEXT.md', () => {
    const r = resolveDocLink('/docs/plan.md#section', 'CONTEXT.md')
    expect(r).toEqual({ type: 'doc', anchor: 'section', path: 'docs/plan.md' })
  })
})
