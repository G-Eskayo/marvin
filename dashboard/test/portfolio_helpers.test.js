import { describe, it, expect } from 'vitest'
import { groupFindingsByRule, parseRulesText, previewDocument, nextComponentName, formatRunTime } from '../src/lib/portfolio.js'

describe('groupFindingsByRule', () => {
  const findings = [
    { page: '/a/ @1440', rule: 'github-button-text', detail: 'x' },
    { page: '/b/ @1440', rule: 'footer-heading-overlap', detail: 'y' },
    { page: '/b/ @1100', rule: 'github-button-text', detail: 'z' }
  ]
  it('groups by rule, biggest group first, keeping every finding', () => {
    const g = groupFindingsByRule(findings)
    expect(g.map((x) => [x.rule, x.items.length])).toEqual([['github-button-text', 2], ['footer-heading-overlap', 1]])
  })
  it('filters by a case-insensitive text match on page, rule or detail', () => {
    expect(groupFindingsByRule(findings, 'FOOTER')).toHaveLength(1)
    expect(groupFindingsByRule(findings, '/a/')[0].items).toHaveLength(1)
    expect(groupFindingsByRule(findings, 'nothing-matches')).toEqual([])
  })
  it('handles no findings and a missing list', () => {
    expect(groupFindingsByRule([])).toEqual([])
    expect(groupFindingsByRule(undefined)).toEqual([])
  })
})

describe('parseRulesText', () => {
  it('accepts a JSON object', () => {
    expect(parseRulesText('{"tolerance_px": 3}')).toEqual({ ok: true, value: { tolerance_px: 3 } })
  })
  it('treats blank text as no overrides', () => {
    expect(parseRulesText('  \n')).toEqual({ ok: true, value: {} })
  })
  it('rejects invalid JSON and non-objects with a readable reason', () => {
    expect(parseRulesText('{oops').ok).toBe(false)
    expect(parseRulesText('[1,2]')).toMatchObject({ ok: false, error: expect.stringMatching(/object/i) })
    expect(parseRulesText('42').ok).toBe(false)
  })
})

describe('previewDocument', () => {
  it('wraps component html in a document using the dev site head', () => {
    const doc = previewDocument('<a class="btn">x</a>', "<base href='/'><link rel='stylesheet' href='a.css'>")
    expect(doc).toContain('<a class="btn">x</a>')
    expect(doc).toContain("<link rel='stylesheet' href='a.css'>")
    expect(doc.indexOf('<head>')).toBeLessThan(doc.indexOf('<body'))
  })
  it('still renders when the head is empty', () => {
    expect(previewDocument('<p>hi</p>', '')).toContain('<p>hi</p>')
  })
})

describe('nextComponentName', () => {
  it('slugifies a typed name into a valid component name', () => {
    expect(nextComponentName('GitHub Button!')).toBe('github-button')
    expect(nextComponentName('  Project   Card  ')).toBe('project-card')
  })
  it('returns an empty string when nothing usable remains', () => {
    expect(nextComponentName('!!!')).toBe('')
  })
})

describe('formatRunTime', () => {
  it('formats an ISO time and tolerates missing input', () => {
    expect(formatRunTime('2026-10-02T15:00:00+00:00')).toMatch(/2026|Oct/)
    expect(formatRunTime(null)).toBe('never')
  })
})
