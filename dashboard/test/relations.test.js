import { describe, it, expect } from 'vitest'
import { extractRefs, buildRelationIndex, linkify } from '../electron/main/relations.js'

describe('extractRefs', () => {
  it('finds ticket refs, qualified or not, but not headings, hex colours or words ending in #n', () => {
    const r = extractRefs('See #12 and G-Eskayo/clarity-captions#7. # Heading, colour #fff, issue#9, and #3abc.')
    expect([...r.tickets].sort((a, b) => a.number - b.number)).toEqual([{ repo: 'G-Eskayo/clarity-captions', number: 7 }, { repo: null, number: 12 }])
  })

  it('finds ADR refs in several spellings and explicit adr paths', () => {
    const r = extractRefs('per ADR 0033, adr-27 and ADR 5; see docs/adr/0026-concurrent-dispatch-smart-merge.md')
    expect(r.adrs.sort((a, b) => a - b)).toEqual([5, 26, 27, 33])
    expect(r.paths).toContain('docs/adr/0026-concurrent-dispatch-smart-merge.md')
  })

  it('finds CONTEXT.md and README.md mentions', () => {
    const r = extractRefs('Update CONTEXT.md; the README.md needs a note')
    expect(r.context).toBe(true)
    expect(r.readme).toBe(true)
  })

  it('ignores anything inside code fences and inline code', () => {
    const r = extractRefs('real #1\n```\nnot #2 and ADR 9\n```\nand `#3` plus ADR 4')
    expect(r.tickets.map((t) => t.number)).toEqual([1])
    expect(r.adrs).toEqual([4])
  })
})

const docs = [
  { project: 'marvin', path: 'CONTEXT.md', label: 'CONTEXT.md', content: 'Boards were ticketed in #117 and G-Eskayo/clarity-captions#7. See ADR 0033.' },
  { project: 'marvin', path: 'docs/adr/0033-health.md', label: '0033-health.md', content: '# Health\nShipped via #115.' },
  { project: 'marvin', path: 'docs/adr/0026-merge.md', label: '0026-merge.md', content: 'x' }
]
const t = (n, over = {}) => ({ repo: 'G-Eskayo/marvin', number: n, title: `T${n}`, state: 'OPEN', body: '', url: `u${n}`, ...over })
const index = (over = {}) =>
  buildRelationIndex({
    tickets: [t(115), t(117, { body: 'Implements ADR 0033. Blocked by #115. Context in CONTEXT.md.' }), t(118, { body: 'unrelated' })],
    prs: [{ repo: 'G-Eskayo/marvin', number: 130, title: 'PR', state: 'OPEN', url: 'p', body: 'Closes #117', files: [{ path: 'docs/adr/0033-health.md' }, { path: 'src/x.js' }] }],
    docs,
    projects: [{ id: 'marvin', repo: 'G-Eskayo/marvin' }, { id: 'clarity-captions', repo: 'G-Eskayo/clarity-captions' }],
    ...over
  })

describe('buildRelationIndex: tickets', () => {
  it('links a ticket to the docs it names, resolving an ADR number to that project\'s file', () => {
    const r = index().forTicket('G-Eskayo/marvin', 117)
    expect(r.docs.map((d) => d.path).sort()).toEqual(['CONTEXT.md', 'docs/adr/0033-health.md'])
    expect(r.docs.find((d) => d.path.includes('0033')).project).toBe('marvin')
  })

  it('ignores an ADR number the project has no file for', () => {
    const r = index({ tickets: [t(1, { body: 'see ADR 0999' })] }).forTicket('G-Eskayo/marvin', 1)
    expect(r.docs).toEqual([])
  })

  it('expresses blocking in both directions', () => {
    const idx = index()
    expect(idx.forTicket('G-Eskayo/marvin', 117).tickets).toContainEqual(expect.objectContaining({ number: 115, relation: 'blocked by' }))
    expect(idx.forTicket('G-Eskayo/marvin', 115).tickets).toContainEqual(expect.objectContaining({ number: 117, relation: 'blocks' }))
  })

  it('shows tickets that only mention it, and the PRs that close it', () => {
    const idx = index()
    expect(idx.forTicket('G-Eskayo/marvin', 115).tickets.map((x) => x.number)).toContain(117)
    expect(idx.forTicket('G-Eskayo/marvin', 117).prs).toContainEqual(expect.objectContaining({ number: 130, relation: 'closed by' }))
  })

  it('never relates a ticket to itself and lists each relation once', () => {
    const idx = index({ tickets: [t(5, { body: 'Mentions #5, and #6 twice: #6' }), t(6)] })
    const r = idx.forTicket('G-Eskayo/marvin', 5)
    expect(r.tickets.map((x) => x.number)).toEqual([6])
  })
})

describe('buildRelationIndex: docs', () => {
  it('backlinks a doc to the tickets and PRs that reference or touch it', () => {
    const r = index().forDoc('marvin', 'docs/adr/0033-health.md')
    expect(r.tickets.map((x) => x.number)).toContain(117)
    expect(r.prs).toContainEqual(expect.objectContaining({ number: 130, relation: 'changed by' }))
  })

  it('links a doc to the tickets it mentions, qualified refs going to the other repo', () => {
    const r = index().forDoc('marvin', 'CONTEXT.md')
    expect(r.tickets).toContainEqual(expect.objectContaining({ repo: 'G-Eskayo/marvin', number: 117, relation: 'mentions' }))
    expect(r.tickets).toContainEqual(expect.objectContaining({ repo: 'G-Eskayo/clarity-captions', number: 7 }))
  })

  it('links docs to other docs through ADR refs, both ways', () => {
    const idx = index()
    expect(idx.forDoc('marvin', 'CONTEXT.md').docs.map((d) => d.path)).toContain('docs/adr/0033-health.md')
    expect(idx.forDoc('marvin', 'docs/adr/0033-health.md').docs.map((d) => d.path)).toContain('CONTEXT.md')
  })

  it('carries ticket titles and state so the UI never shows a bare number', () => {
    const r = index().forDoc('marvin', 'CONTEXT.md')
    expect(r.tickets.find((x) => x.number === 117)).toMatchObject({ title: 'T117', state: 'OPEN' })
  })
})

describe('buildRelationIndex: PRs', () => {
  it('lists the docs a PR changes and the ticket it closes', () => {
    const r = index().forPr('G-Eskayo/marvin', 130)
    expect(r.docs.map((d) => d.path)).toEqual(['docs/adr/0033-health.md'])
    expect(r.tickets).toContainEqual(expect.objectContaining({ number: 117, relation: 'closes' }))
  })
})

describe('linkify', () => {
  const ctx = { repo: 'G-Eskayo/marvin', project: 'marvin', adrs: { 33: 'docs/adr/0033-health.md' } }

  it('turns ticket and ADR refs into dash:// links', () => {
    const out = linkify('See #117 and ADR 0033 and G-Eskayo/clarity-captions#7.', ctx)
    expect(out).toContain('[#117](dash://ticket/G-Eskayo/marvin/117)')
    expect(out).toContain('[ADR 0033](dash://doc/marvin/docs/adr/0033-health.md)')
    expect(out).toContain('[G-Eskayo/clarity-captions#7](dash://ticket/G-Eskayo/clarity-captions/7)')
  })

  it('leaves code, existing links, unresolvable ADRs and headings\' hash alone', () => {
    const src = '```\n#5 ADR 0033\n```\n`#6` [x #7](http://a) ADR 0999\n# Title'
    expect(linkify(src, ctx)).toBe(src)
  })
})
