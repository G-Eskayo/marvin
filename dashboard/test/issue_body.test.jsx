import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { prepareIssueBody, prepareStats, safeUrl, isKeySection } from '../src/lib/issueBody.js'
import IssueBody, { sameIssueBody } from '../src/components/IssueBody.jsx'

// Ticket and PR descriptions render as formatted reading, not a scrolling text box (owner, 2026-10-09).
const render = (props) => renderToStaticMarkup(<IssueBody {...props} />)

describe('prepareIssueBody: GitHub body → safe markdown', () => {
  it('drops HTML comments (they showed as literal text)', () => {
    expect(prepareIssueBody('Hi <!-- secret --> there\n<!-- a\nmulti-line -->\nend')).toBe('Hi  there\n\nend')
  })

  it('cuts out the Decisions section (rendered by the Decisions component), heading included, up to the next section', () => {
    const body = 'Intro\n\n## Decisions\n<!-- marvin:decisions -->\n### dance: Which?\n- [ ] A\n- [ ] B\n\n## After\nkept'
    const out = prepareIssueBody(body)
    expect(out).not.toMatch(/dance|Which\?|Decisions/)
    expect(out).toContain('Intro')
    expect(out).toContain('## After\nkept')
  })

  it('keeps the Decisions section when asked to (a page with no Decisions component)', () => {
    expect(prepareIssueBody('## Decisions\n<!-- marvin:decisions -->\n### a: Q\n- [ ] x', { stripDecisions: false })).toContain('### a: Q')
  })

  it('turns the HTML GitHub bodies use into markdown, and drops every other tag', () => {
    const out = prepareIssueBody('<img src="https://x/y.png" alt="Mock [1]"> <br/> <details><summary>More</summary>inside</details> <b>bold</b> <video src="https://x/r.mp4"></video>')
    expect(out).toContain('![Mock 1](https://x/y.png)')
    expect(out).toContain('**More**')
    expect(out).toContain('inside')
    expect(out).toContain('bold')
    expect(out).toContain('[▶ Recording](https://x/r.mp4)')
    expect(out).not.toMatch(/<\/?(details|summary|b|video|br)\b/i)
  })

  it('never rewrites code: fenced blocks and inline code keep their HTML', () => {
    const body = 'Use `<br>` here\n\n```html\n<!-- keep -->\n<img src=x>\n```\n\nafter <i>x</i>'
    const out = prepareIssueBody(body)
    expect(out).toContain('`<br>`')
    expect(out).toContain('```html\n<!-- keep -->\n<img src=x>\n```')
    expect(out).toContain('after x')
  })

  it('a <script> or event-handler tag never survives as markup', () => {
    const out = prepareIssueBody('<script>alert(1)</script><img src=x onerror=alert(1)><iframe src="https://evil"></iframe>')
    expect(out).not.toMatch(/<script|onerror|<iframe/i)
  })

  it('cuts a huge body off with a note instead of freezing the page', () => {
    const out = prepareIssueBody('x'.repeat(300_000))
    expect(out.length).toBeLessThan(201_000)
    expect(out).toContain('cut off')
  })

  it('prepares each body once: the same text again (a poll tick) is a cache hit', () => {
    const body = `memo test ${Math.random()}`
    const before = prepareStats.transforms
    const a = prepareIssueBody(body)
    const b = prepareIssueBody(body)
    expect(a).toBe(b)
    expect(prepareStats.transforms - before).toBe(1)
  })

  it('handles empty and null bodies', () => {
    expect(prepareIssueBody(null)).toBe('')
    expect(prepareIssueBody('')).toBe('')
  })
})

describe('safeUrl: links in a ticket are untrusted', () => {
  it('keeps web, mail, in-dashboard, anchors, images and repo-relative paths', () => {
    for (const u of ['https://github.com/x', 'http://a.b', 'mailto:a@b.c', 'dash://ticket/G-Eskayo/marvin/1', '#top', 'docs/x.png', 'data:image/png;base64,AA']) {
      expect(safeUrl(u)).toBe(u)
    }
  })
  it('refuses javascript:, vbscript:, file:, data:text and protocol-relative links', () => {
    for (const u of ['javascript:alert(1)', ' JavaScript:alert(1)', 'vbscript:x', 'file:///etc/passwd', 'data:text/html,<script>', '//evil.com/x']) {
      expect(safeUrl(u)).toBeNull()
    }
  })
})

describe('IssueBody rendering', () => {
  it('renders every GitHub-flavored element as formatted HTML, not a <pre> box', () => {
    const body = [
      '# Title', '## What to build', 'Plain **bold** and `code`.', '',
      '- one', '- two', '', '1. first', '2. second', '',
      '- [ ] open task', '- [x] done task', '',
      '| a | b |', '|---|---|', '| 1 | 2 |', '',
      '> quoted', '', '```', 'block', '```', '', '---', '', '[site](https://example.com)'
    ].join('\n')
    const html = render({ body })
    for (const tag of ['<h1', '<h2', '<strong', '<code', '<ul', '<ol', '<table', '<th', '<td', '<blockquote', '<pre', '<hr', 'href="https://example.com"']) {
      expect(html).toContain(tag)
    }
    expect(html).toContain('aria-label="done"')
    expect(html).toContain('aria-label="not done"')
    expect(html).not.toContain('whitespace-pre-wrap')
    expect(html).toContain('max-w-[70ch]')
  })

  it('opens web links outside the app', () => {
    expect(render({ body: '[x](https://a.b)' })).toMatch(/target="_blank" rel="noreferrer noopener"/)
  })

  it('drops a javascript: link to plain text', () => {
    const html = render({ body: '[click](javascript:alert(1))' })
    expect(html).not.toMatch(/javascript:/i)
    expect(html).toContain('click')
  })

  it('never shows the raw Decisions marker or questions (the Decisions component shows them)', () => {
    const html = render({ body: 'Intro\n\n## Decisions\n<!-- marvin:decisions -->\n### dance: Which?\n- [ ] A' })
    expect(html).not.toContain('marvin:decisions')
    expect(html).not.toContain('Which?')
    expect(html).toContain('Intro')
  })

  it('links ticket references and shows the referenced title when the page already has it', () => {
    const html = render({ body: 'Blocked by #12 and G-Eskayo/marvin#7.', ctx: { repo: 'G-Eskayo/clarity-captions' }, titles: { 'G-Eskayo/clarity-captions#12': 'Stop hangs' } })
    expect(html).toContain('#12')
    expect(html).toContain('Stop hangs')
    expect(html).toContain('G-Eskayo/marvin#7')
    expect(html.match(/bg-blue-950/g)).toHaveLength(2)
  })

  it('gives the ticket template sections a quiet accent', () => {
    const html = render({ body: "## What to build\nx\n## Acceptance criteria\ny\n## How we'll try to break it\nz\n## Other\nw" })
    expect(html.match(/data-key-section="true"/g)).toHaveLength(3)
    expect(isKeySection('Blocked by')).toBe(true)
    expect(isKeySection('Random heading')).toBe(false)
  })

  it('images load through the authenticated loader (private repos), with a placeholder first', () => {
    const loadImage = vi.fn(() => new Promise(() => {}))
    const html = render({ body: '![Mock](docs/m.png)', ctx: { repo: 'G-Eskayo/finance-os' }, headRef: 'feature/x', loadImage })
    expect(html).toContain('aria-label="Loading image"')
  })

  it('an image with an unsafe source shows a plain note, never a broken tag', () => {
    const html = render({ body: '![x](javascript:alert(1))' })
    expect(html).not.toMatch(/javascript:/i)
  })

  it('says so when there is no description', () => {
    expect(render({ body: '' })).toContain('(no description)')
  })

  it('a very large real-world body renders', () => {
    const big = Array.from({ length: 400 }, (_, i) => `## Section ${i}\n- item ${i}\n- [ ] task ${i}\n\nParagraph with #${i} and **bold** text.`).join('\n\n')
    const t = Date.now()
    const html = render({ body: big, ctx: { repo: 'G-Eskayo/marvin' } })
    expect(html).toContain('Section 399')
    expect(Date.now() - t).toBeLessThan(3000)
  })
})

describe('memoization: same body, no re-render', () => {
  it('treats identical props as equal (a poll tick with the same body skips rendering)', () => {
    const ctx = { repo: 'r' }
    const titles = {}
    const a = { body: 'x', updatedAt: '1', ctx, titles }
    expect(sameIssueBody(a, { ...a, onLink: () => {} })).toBe(true)
    expect(sameIssueBody(a, { ...a, body: 'y' })).toBe(false)
    expect(sameIssueBody(a, { ...a, updatedAt: '2' })).toBe(false)
    expect(sameIssueBody(a, { ...a, ctx: { repo: 'r' } })).toBe(true)
    expect(sameIssueBody(a, { ...a, ctx: { repo: 'other' } })).toBe(false)
  })
})
