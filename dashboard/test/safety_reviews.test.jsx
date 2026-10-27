import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createSafetyReviews, cleanList } from '../electron/main/safety_reviews.js'
import { sourceLabel, shortDate, pickCurrent, progressOf, validNote, NOTE_CAP, excerptMarkdown } from '../src/lib/safety_reviews.js'
import { ReviewCard, SafetyReviewsView, EntryMarkdown } from '../src/components/SafetyReviews.jsx'

// Health ▸ Safety reviews (approved 2026-10-26): the quarantine's entries one card at a time; Fine / Fix it / Block
// tick that entry's box through process_quarantine_reviews.py (its own tests cover the file). These try to break the
// IPC layer and the card: hostile entry text, malformed script output, bad answers, stale cards.

const E = (over = {}) => ({
  id: '0123456789abcdef', date: '2026-10-24', loop: 'research_colony', score: 0.35, tau: 0.3,
  reason: 'possible unsupported claim', excerpt: 'A method for choosing which outputs get a human audit',
  body: 'A method for choosing which outputs get a human audit, in full.', truncated: false, ...over
})

describe('createSafetyReviews (main-process side)', () => {
  it('list passes the script output through, cleaned', async () => {
    const calls = []
    const s = createSafetyReviews({ run: async (args) => (calls.push(args), JSON.stringify({ entries: [E()], pending: 1, unreadable: 0 })) })
    expect(await s.list()).toEqual({ entries: [E()], pending: 1, unreadable: 0 })
    expect(calls).toEqual([['list']])
  })

  it('a script failure or garbage output is an empty list with an error, never a throw', async () => {
    const boom = createSafetyReviews({ run: async () => { throw new Error('python missing') } })
    expect(await boom.list()).toMatchObject({ entries: [], pending: 0, error: expect.any(String) })
    const junk = createSafetyReviews({ run: async () => 'Traceback (most recent call last)' })
    expect(await junk.list()).toMatchObject({ entries: [], pending: 0, error: expect.any(String) })
  })

  it('wrong-shaped entries are dropped or coerced to safe values', () => {
    const out = cleanList({
      entries: [E(), null, 7, { id: 'x' }, E({ id: 'fedcba9876543210', score: '0.9', reason: { html: '<b>' }, body: ['a'] })],
      pending: 'lots'
    })
    expect(out.entries.map((e) => e.id)).toEqual(['0123456789abcdef', 'fedcba9876543210'])
    expect(out.entries[1]).toMatchObject({ score: null, reason: '', body: '' })
    expect(out.pending).toBe(2)
  })

  it('answer sends only checked arguments, as separate argv items (no shell)', async () => {
    const calls = []
    const s = createSafetyReviews({ run: async (args) => (calls.push(args), '{"status":"answered","remaining":3}') })
    expect(await s.answer('0123456789abcdef', 'modify', 'tighten; $(rm -rf ~)')).toEqual({ status: 'answered', remaining: 3 })
    expect(calls[0]).toEqual(['answer', '--id', '0123456789abcdef', '--kind', 'modify', '--text', 'tighten; $(rm -rf ~)'])
    await s.answer('0123456789abcdef', 'deny')
    expect(calls[1]).toEqual(['answer', '--id', '0123456789abcdef', '--kind', 'deny'])
  })

  it('refuses a bad id, kind, empty or oversized note before running anything', async () => {
    const calls = []
    const s = createSafetyReviews({ run: async (args) => (calls.push(args), '{}') })
    expect((await s.answer('--kind=deny', 'approve')).status).toBe('invalid')
    expect((await s.answer('0123456789abcdef', 'rm')).status).toBe('invalid')
    expect(await s.answer('0123456789abcdef', 'modify', '   ')).toEqual({ status: 'invalid', reason: 'empty' })
    expect(await s.answer('0123456789abcdef', 'modify', 'x'.repeat(NOTE_CAP + 1))).toEqual({ status: 'invalid', reason: 'too-long' })
    expect((await s.answer({ toString: () => 'x' }, 'approve')).status).toBe('invalid')
    expect(calls).toEqual([])
  })

  it('an answer whose script fails reports failed, never throws', async () => {
    const s = createSafetyReviews({ run: async () => { throw new Error('locked') } })
    expect(await s.answer('0123456789abcdef', 'approve')).toMatchObject({ status: 'failed' })
  })
})

describe('display rules', () => {
  it('source and date read like the approved card', () => {
    expect(sourceLabel('research_colony')).toBe('Research colony')
    expect(sourceLabel('self_improve')).toBe('Self improve')
    expect(sourceLabel('')).toBe('Unknown source')
    expect(shortDate('2026-10-24')).toBe('Oct 24')
    expect(shortDate('2026-01-01')).toBe('Jan 1')
    expect(shortDate('not a date')).toBe('not a date')
  })

  it('the current card stays put while it is still pending, else the first one', () => {
    const a = E({ id: 'a'.repeat(16) }), b = E({ id: 'b'.repeat(16) })
    expect(pickCurrent([a, b], 'b'.repeat(16))).toBe(b)
    expect(pickCurrent([a, b], 'c'.repeat(16))).toBe(a)
    expect(pickCurrent([], 'a')).toBe(null)
  })

  it('progress counts this session’s answers into the total, so "N of 97" holds as entries go', () => {
    expect(progressOf(0, 97)).toEqual({ position: 1, total: 97, answered: 0, left: 97 })
    expect(progressOf(9, 88)).toEqual({ position: 10, total: 97, answered: 9, left: 88 })
    expect(progressOf(97, 0)).toEqual({ position: 97, total: 97, answered: 97, left: 0 })
  })

  it('a note is valid only with text', () => {
    expect(validNote('')).toBe(false)
    expect(validNote(' \n ')).toBe(false)
    expect(validNote('drop claim 2')).toBe(true)
    expect(validNote('x'.repeat(NOTE_CAP + 1))).toBe(false)
  })
})

describe('the card', () => {
  const html = (props) => renderToStaticMarkup(<ReviewCard entry={E()} onAnswer={() => {}} {...props} />)

  it('shows source, date, risk, limit, reason, excerpt and the three answers', () => {
    const out = html()
    for (const s of ['Research colony · Oct 24', 'Risk 0.35', '(limit 0.30)', 'Why held: possible unsupported claim',
      'A method for choosing which outputs get a human audit', 'Show full item ▾', 'Fine, let it through', 'Fix it', 'Block']) {
      expect(out).toContain(s)
    }
  })

  it('no reason means no "Why held" line', () => {
    expect(renderToStaticMarkup(<ReviewCard entry={E({ reason: '' })} onAnswer={() => {}} />)).not.toContain('Why held')
  })

  it('expanded shows the whole item; fixing shows the text box', () => {
    expect(html({ initialExpanded: true })).toContain('in full.')
    const fixing = html({ initialFixing: true })
    expect(fixing).toContain('<textarea')
    expect(fixing).toContain(`maxLength="${NOTE_CAP}"`)
    expect(fixing).toMatch(/<button[^>]*disabled=""[^>]*>Submit<\/button>/)
  })

  it('script and HTML in the entry render as text, never markup', () => {
    const evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    const out = renderToStaticMarkup(
      <ReviewCard entry={E({ excerpt: evil, body: evil, reason: '<b onclick=x>r</b>', loop: '<i>x</i>' })} onAnswer={() => {}} initialExpanded />
    )
    expect(out).not.toContain('<script>')
    expect(out).not.toContain('<img')
    expect(out).not.toContain('<b onclick')
    expect(out).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
  })

  it('the excerpt and the full item are rendered markdown, not raw text', () => {
    const md = '## Directly Relevant\n\n**Bold title** — text with a [link](https://example.com/x).\n\n- one\n- two\n\n> quoted'
    const card = renderToStaticMarkup(<ReviewCard entry={E({ body: md, excerpt: 'plain' })} onAnswer={() => {}} />)
    expect(card).toMatch(/<h2[^>]*>Directly Relevant<\/h2>/)
    expect(card).toMatch(/<strong[^>]*>Bold title<\/strong>/)
    expect(card).not.toContain('**')
    const full = renderToStaticMarkup(<ReviewCard entry={E({ body: md })} onAnswer={() => {}} initialExpanded />)
    expect(full).toMatch(/<li[^>]*>one<\/li>/)
    expect(full).toMatch(/<blockquote[^>]*>/)
    expect(full).toContain('href="https://example.com/x" target="_blank" rel="noreferrer noopener"')
  })

  it('a huge item is shown cut, saying so', () => {
    expect(html({ entry: E({ truncated: true }), initialExpanded: true })).toContain('…')
  })
})

describe('the view', () => {
  it('heading counts "N of total", with the progress line and footer', () => {
    const out = renderToStaticMarkup(<SafetyReviewsView data={{ entries: [E()], pending: 88 }} answered={9} onAnswer={() => {}} />)
    expect(out).toContain('Safety reviews (10 of 97)')
    expect(out).toContain('9 answered · 88 to go')
    expect(out).toContain('Your answers teach the filter.')
  })

  it('nothing pending, still loading and a read error each say so', () => {
    expect(renderToStaticMarkup(<SafetyReviewsView data={{ entries: [], pending: 0 }} answered={0} onAnswer={() => {}} />)).toContain('Nothing waiting for review.')
    expect(renderToStaticMarkup(<SafetyReviewsView data={null} answered={0} onAnswer={() => {}} />)).toContain('Loading…')
    expect(renderToStaticMarkup(<SafetyReviewsView data={{ entries: [], pending: 0, error: 'python missing' }} answered={0} onAnswer={() => {}} />)).toContain('python missing')
  })
})

describe('entry markdown is untrusted (model output)', () => {
  const md = (text) => renderToStaticMarkup(<EntryMarkdown text={text} />)

  it('script tags and inline HTML render as escaped text', () => {
    const out = md('hi <script>alert(1)</script> and <b onclick="x()">b</b>')
    expect(out).not.toMatch(/<script|<b[ >]|<[^>]*onclick=/i)
    expect(out).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
  })

  it('a raw HTML block renders as text, not elements', () => {
    const out = md('<div onmouseover="x()"><iframe src="https://evil.example"></iframe></div>\n\n<style>body{display:none}</style>')
    expect(out).not.toMatch(/<div[^>]*onmouseover|<iframe|<style|<[^>]*onmouseover=/i)
    expect(out).toContain('&lt;iframe')
  })

  it('images never load: <img onerror> is text, markdown images show their alt text only', () => {
    const out = md('<img src=x onerror=alert(1)>\n\n![tracker](https://evil.example/pixel.png) ![d](data:image/png;base64,AAAA)')
    expect(out).not.toMatch(/<img/i)
    expect(out).toContain('[image: tracker]')
    expect(out).toContain('&lt;img src=x onerror=alert(1)&gt;')
  })

  it('javascript:, data:, file: and vbscript: links are not links', () => {
    for (const href of ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'data:text/html,<script>alert(1)</script>', 'file:///etc/passwd', 'vbscript:x', ' javascript:alert(1)']) {
      const out = md(`[click](${href})`)
      expect(out, href).not.toMatch(/<a /)
      expect(out, href).toContain('click')
    }
    expect(md('<javascript:alert(1)>')).not.toMatch(/href="javascript/i)
  })

  it('in-app links from entry text are not followed (dash://, relative)', () => {
    expect(md('[t](dash://ticket/o/r/1) [d](docs/x.md)')).not.toMatch(/<a /)
  })

  it('a huge table renders (as a table) without throwing', () => {
    const rows = Array.from({ length: 2000 }, (_, i) => `| ${i} | <b>${i}</b> |`).join('\n')
    const out = md(`| a | b |\n|---|---|\n${rows}`)
    expect(out).toContain('<table')
    expect(out).not.toContain('<b>')
  })

  it('an unclosed code fence and deeply nested quotes stay contained', () => {
    const fence = md('before\n\n```js\n<script>alert(1)</script>\nno end')
    expect(fence).toMatch(/<pre/)
    expect(fence).toContain('&lt;script&gt;')
    const nested = md('>'.repeat(200) + ' deep')
    expect(nested).toContain('deep')
    expect(nested).toMatch(/<blockquote/)
  })
})

describe('excerptMarkdown: the first part, cut cleanly', () => {
  it('a short entry is whole and not cut', () => {
    expect(excerptMarkdown('## H\n\ntext')).toEqual({ text: '## H\n\ntext', cut: false })
  })

  it('cuts at a paragraph boundary within the budget', () => {
    const body = '## H\n\n' + 'a'.repeat(200) + '\n\n' + 'b'.repeat(400) + '\n\nlast'
    const { text, cut } = excerptMarkdown(body, 300)
    expect(cut).toBe(true)
    expect(text).toBe('## H\n\n' + 'a'.repeat(200))
  })

  it('never cuts inside a code fence; an unclosed fence is closed', () => {
    const body = 'intro\n\n```\n' + Array.from({ length: 50 }, (_, i) => `line ${i}`).join('\n') + '\n```\n\nafter'
    const { text } = excerptMarkdown(body, 60)
    expect(text.match(/```/g).length % 2).toBe(0)
    const open = excerptMarkdown('```\n' + 'x\n'.repeat(500), 50).text
    expect(open.match(/```/g).length).toBe(2)
  })

  it('a huge first table is cut at a row, still a table', () => {
    const body = '| a | b |\n|---|---|\n' + Array.from({ length: 500 }, (_, i) => `| ${i} | x |`).join('\n')
    const { text, cut } = excerptMarkdown(body, 200)
    expect(cut).toBe(true)
    expect(text.split('\n').every((l) => l.startsWith('|'))).toBe(true)
    expect(renderToStaticMarkup(<EntryMarkdown text={text} />)).toContain('<table')
  })

  it('never cuts mid-line: a single huge line is kept whole (the card clips it visually)', () => {
    const line = '**bold** ' + 'word '.repeat(400)
    expect(excerptMarkdown(line + '\n\nnext', 100)).toEqual({ text: line, cut: true })
  })

  it('does not end on a heading with nothing under it', () => {
    const body = '## One\n\n' + 'a'.repeat(150) + '\n\n## Two\n\n' + 'b'.repeat(400)
    expect(excerptMarkdown(body, 200)).toEqual({ text: '## One\n\n' + 'a'.repeat(150), cut: true })
  })

  it('empty or non-string input is empty', () => {
    expect(excerptMarkdown('')).toEqual({ text: '', cut: false })
    expect(excerptMarkdown(null)).toEqual({ text: '', cut: false })
  })
})
