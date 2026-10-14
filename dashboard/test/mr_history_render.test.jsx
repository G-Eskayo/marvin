import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { HistoryList, HistoryRow } from '../src/components/MrHistory.jsx'
import { ViewToggle } from '../src/components/MrReview.jsx'
import MrDetail from '../src/components/MrDetail.jsx'

// marvin#419: the Merged view and the read-only detail.
const noop = () => {}
const NOW = new Date('2026-10-13T20:00:00')
const at = (s) => new Date(s).toISOString()
const rows = [
  { kind: 'merged', url: 'u414', number: 414, title: 'Fix red main', repo: 'G-Eskayo/marvin', at: at('2026-10-13T12:47:00'), by: 'you' },
  { kind: 'refused', url: 'u400', number: 400, title: 'Implement #218', repo: 'G-Eskayo/marvin', at: at('2026-10-13T12:46:00'), reason: 'main was failing' },
  { kind: 'merged', url: 'u135', number: 135, title: 'ADR 0024 beta ingest', repo: 'G-Eskayo/clarity-captions', at: at('2026-10-12T11:51:00'), by: 'unrecorded' }
]

describe('HistoryList', () => {
  const html = renderToStaticMarkup(<HistoryList data={{ rows, updatedAt: 1, errors: [] }} page={0} setPage={noop} onOpen={noop} now={NOW} />)
  it('groups by day with Today and Yesterday', () => {
    expect(html).toContain('>Today<')
    expect(html).toContain('>Yesterday<')
  })
  it('every row pairs its number with its title, project and who merged it', () => {
    expect(html).toContain('#414</span> Fix red main')
    expect(html).toContain('clarity-captions')
    expect(html).toContain('>you<')
    expect(html).toContain('>not recorded<')
  })
  it('a refused Approve shows as ✗ with its plain reason', () => {
    expect(html).toContain('data-kind="refused"')
    expect(html).toContain('refused: main was failing')
  })
  it('one page has no page controls; more than 5 days does', () => {
    expect(html).not.toContain('Older →')
    const many = Array.from({ length: 7 }, (_, i) => ({ ...rows[0], url: `x${i}`, at: at(`2026-10-0${i + 1}T10:00:00`) }))
    expect(renderToStaticMarkup(<HistoryList data={{ rows: many, updatedAt: 1 }} page={0} setPage={noop} onOpen={noop} now={NOW} />)).toContain('Page 1 of 2')
  })
  it('empty: says reading, or nothing yet once read', () => {
    expect(renderToStaticMarkup(<HistoryList data={{ rows: [], updatedAt: null }} page={0} setPage={noop} onOpen={noop} />)).toContain('Reading merge history')
    expect(renderToStaticMarkup(<HistoryList data={{ rows: [], updatedAt: 5 }} page={0} setPage={noop} onOpen={noop} />)).toContain('Nothing merged or refused yet')
  })
})

describe('ViewToggle', () => {
  it('Open shows its count; the chosen view is pressed', () => {
    const html = renderToStaticMarkup(<ViewToggle view="merged" setView={noop} openCount={3} />)
    expect(html).toMatch(/aria-pressed="false"[^>]*>Open \(3\)</)
    expect(html).toMatch(/aria-pressed="true"[^>]*>Merged</)
  })
})

describe('MrDetail read-only', () => {
  const pr = { number: 414, title: 'Fix red main', url: 'https://github.com/G-Eskayo/marvin/pull/414', repo: 'G-Eskayo/marvin', key: 'k', hasSchema: false, rawBody: 'body',
    evidence: null, images: [], decisions: { present: true, questions: [{ id: 'a', text: 'q' }] }, readOnly: true, state: 'MERGED', mergedAt: '2026-10-13T18:47:50Z', checks: { state: 'none' } }
  const html = renderToStaticMarkup(<MrDetail pr={pr} onBack={noop} />)
  it('has no Approve or Deny, says merged and read-only', () => {
    expect(html).not.toMatch(/>Approve</)
    expect(html).not.toMatch(/>Deny</)
    expect(html).toContain('data-readonly="1"')
    expect(html).toContain('read-only')
  })
  it('opened from a refused row, it says when and why the Approve was refused', () => {
    const r = renderToStaticMarkup(<MrDetail pr={{ ...pr, state: 'OPEN', refusal: { at: '2026-10-13T19:05:24Z', reason: 'tests failed', message: 'test_machine_resources.py::test_pathologically_huge_input' } }} onBack={noop} />)
    expect(r).toContain('data-refusal="1"')
    expect(r).toContain('tests failed')
    expect(r).toContain('test_pathologically_huge_input')
  })
  it('does not offer to answer decisions on a merged PR', () => {
    expect(html).not.toContain('Submit')
  })
})
