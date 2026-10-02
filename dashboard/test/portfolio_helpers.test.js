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

import { initialData, buildOptions, fieldInputType, groupTemplates, slugify, projectDefaults, countByType } from '../src/lib/portfolio.js'

describe('template form helpers', () => {
  const page = { fields: [{ name: 'TITLE', type: 'text', required: true }, { name: 'LABEL', type: 'text', default: 'View on GitHub' }, { name: 'BODY_HTML', type: 'html' }] }

  it('initialData seeds each field with its default (or empty)', () => {
    expect(initialData(page)).toEqual({ TITLE: '', LABEL: 'View on GitHub', BODY_HTML: '' })
    expect(initialData({})).toEqual({})
  })

  it('fieldInputType picks a textarea for html and long text, url and text otherwise', () => {
    expect(fieldInputType({ type: 'html' })).toBe('textarea')
    expect(fieldInputType({ type: 'url' })).toBe('url')
    expect(fieldInputType({ type: 'text' })).toBe('text')
    expect(fieldInputType({})).toBe('text')
  })

  it('buildOptions turns slot choices into the renderer\'s options shape, dropping empty slots', () => {
    const choices = { actions: [{ template: 'button-github', data: { REPO_URL: 'https://github.com/G-Eskayo/x' } }], extras: [] }
    expect(buildOptions(choices)).toEqual({ actions: [{ template: 'button-github', data: { REPO_URL: 'https://github.com/G-Eskayo/x' } }] })
    expect(buildOptions({})).toEqual({})
  })

  it('groupTemplates orders pages, then components, then buttons, and omits empty groups', () => {
    const g = groupTemplates([{ id: 'b', kind: 'button' }, { id: 'p', kind: 'page' }, { id: 'c', kind: 'component' }, { id: 'p2', kind: 'page' }])
    expect(g.map((x) => [x.kind, x.items.map((i) => i.id)])).toEqual([['page', ['p', 'p2']], ['component', ['c']], ['button', ['b']]])
    expect(groupTemplates([])).toEqual([])
  })
})

describe('new project wizard helpers', () => {
  it('slugify makes a safe url slug from a title', () => {
    expect(slugify('Resume Tailor!')).toBe('resume-tailor')
    expect(slugify('  MITRE ATT&CK Techniques ')).toBe('mitre-att-ck-techniques')
    expect(slugify('')).toBe('')
  })

  it('projectDefaults starts every field blank with the first category and no actions', () => {
    const d = projectDefaults()
    expect(d).toMatchObject({ title: '', slug: '', category: 'AI & Machine Learning', actions: [] })
    expect(Object.keys(d)).toEqual(expect.arrayContaining(['subtitle', 'description', 'body_html', 'hero_image_url', 'thumbnail', 'stack_csv']))
  })
})

describe('countByType', () => {
  it('counts pages per type for the inventory header', () => {
    expect(countByType([{ type: 'project' }, { type: 'project' }, { type: 'hub' }])).toEqual({ project: 2, hub: 1 })
    expect(countByType(undefined)).toEqual({})
  })
})

describe('previewDocument hides WordPress shortcodes', () => {
  it('removes fusion shortcode tokens so only the real markup shows in a preview', () => {
    const doc = previewDocument('[fusion_builder_container type="flex"][fusion_text]<p>Hello</p>[/fusion_text][/fusion_builder_container]', '')
    expect(doc).toContain('<p>Hello</p>')
    expect(doc).not.toMatch(/\[\/?fusion_/)
  })
  it('leaves ordinary square brackets alone', () => {
    expect(previewDocument('<p>a [b] c</p>', '')).toContain('a [b] c')
  })
})

import { buttonVerdict } from '../src/lib/portfolio.js'
describe('buttonVerdict', () => {
  it('accepts the three canonical buttons', () => {
    for (const t of ['Discover', 'View on GitHub', 'Download report'])
      expect(buttonVerdict({ texts: [t], classes: 'btn btn-default' }).ok).toBe(true)
  })
  it('flags other wording or non-button styling', () => {
    expect(buttonVerdict({ texts: ['GitHub'], classes: 'btn btn-default' })).toEqual({ ok: false, label: 'off-canon text' })
    expect(buttonVerdict({ texts: ['View on GitHub'], classes: 'link' })).toEqual({ ok: false, label: 'off-canon style' })
  })
})

import { inventoryIsStale } from '../src/lib/portfolio.js'
describe('inventoryIsStale', () => {
  const now = Date.parse('2026-10-02T12:00:00Z')
  it('is stale when never crawled or unparseable', () => {
    expect(inventoryIsStale(null, now)).toBe(true)
    expect(inventoryIsStale('garbage', now)).toBe(true)
  })
  it('is fresh within the window and stale beyond it', () => {
    expect(inventoryIsStale('2026-10-02T11:55:00Z', now)).toBe(false)
    expect(inventoryIsStale('2026-10-02T11:40:00Z', now)).toBe(true)
  })
})

describe('previewDocument width', () => {
  it('honours an explicit pixel width over the default', () => {
    expect(previewDocument('<p/>', '', { width: 260 })).toContain('max-width:260px')
    expect(previewDocument('<p/>', '', { wide: true })).toContain('max-width:none')
  })
})

describe('previewDocument body class', () => {
  it('applies the site body class carried in the head, and wraps content like the theme does', () => {
    const doc = previewDocument('<p/>', '<meta name="preview-body-class" content="fusion-top-header single">')
    expect(doc).toContain('<body class="fusion-top-header single"')
    expect(doc).toContain('id="wrapper"')
  })
})
