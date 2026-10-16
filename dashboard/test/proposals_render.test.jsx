import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ProposalsView, ProposalCard, DismissUntil, DismissReason } from '../src/components/ProposalsSection.jsx'
import { ViewToggle } from '../src/components/MrReview.jsx'

const P = {
  id: 'hand-small-jobs', title: 'Hand small jobs to the local model', problem: 'Every job uses a full Claude call.',
  fix: 'Send simple jobs to the Mini.', why: 'Fewer tokens.', size: 'Large', area: 'Cost', north_star: 1,
  north_star_name: 'Minimise resources', source: 'Research colony', added: '2026-10-14', technical: 'Ollama.',
  status: { state: 'open' }
}
const api = { proposals: { act: async () => ({ ok: true }) }, marvin: { openSession: async () => ({ ok: true }) } }
const list = (proposals, problems = []) => ({ kind: 'list', proposals, problems })
const html = (el) => renderToStaticMarkup(el)

describe('Proposals section states', () => {
  it('loading', () => {
    expect(html(<ProposalsView state={{ kind: 'loading' }} api={api} />)).toContain('Loading proposals')
  })

  it('error offers a retry and says what failed', () => {
    const out = html(<ProposalsView state={{ kind: 'error', error: 'Traceback: boom' }} api={api} />)
    expect(out).toContain('The proposals store didn’t answer on this Mac')
    expect(out).toContain('Details: Traceback: boom')
    expect(out).toContain('Try again')
  })

  it('empty says where ideas will come from, not a blank page', () => {
    const out = html(<ProposalsView state={list([])} api={api} />)
    expect(out).toContain('data-empty')
    expect(out).toContain('research colony')
  })

  it('a card shows the plain lines, tags, source and every action', () => {
    const out = html(<ProposalsView state={list([P])} api={api} />)
    for (const s of ['Problem', 'Every job uses a full Claude call.', 'Fix', 'Why it matters', 'Large', 'Cost', '★ Minimise resources',
      'Research colony · Oct 14, 2026', 'Make it a ticket', 'Ask MARVIN', 'Snooze ▾', 'Dismiss ▾', '▸ Technical details']) {
      expect(out, s).toContain(s)
    }
    expect(out).not.toContain('Ollama.') // folded away until opened
  })

  it('optional fields can be missing without breaking the card', () => {
    const bare = { ...P, size: undefined, area: undefined, source: undefined, technical: undefined }
    const out = html(<ProposalCard proposal={bare} api={api} onDone={() => {}} />)
    expect(out).toContain('★ Minimise resources')
    expect(out).not.toContain('Technical details')
    expect(out).toContain('Oct 14, 2026')
  })

  it('hostile text is shown as text, never as markup', () => {
    const evil = { ...P, title: '<img src=x onerror=alert(1)>', problem: '<script>alert(1)</script>' }
    const out = html(<ProposalCard proposal={evil} api={api} onDone={() => {}} />)
    expect(out).not.toContain('<script>')
    expect(out).not.toContain('<img src=x')
    expect(out).toContain('&lt;script&gt;')
  })

  it('very long text wraps instead of overflowing', () => {
    const out = html(<ProposalCard proposal={{ ...P, problem: 'x'.repeat(600) }} api={api} onDone={() => {}} />)
    expect(out).toContain('break-words')
  })

  it('a proposal that came back says why', () => {
    const out = html(<ProposalCard proposal={{ ...P, returned: 'Snooze ended 2026-10-22' }} api={api} onDone={() => {}} />)
    expect(out).toContain('Back again: Snooze ended 2026-10-22')
  })

  it('unreadable files are reported, capped at five names', () => {
    const problems = Array.from({ length: 7 }, (_, i) => ({ file: `bad-${i}.json`, error: 'not JSON' }))
    const out = html(<ProposalsView state={list([P], problems)} api={api} />)
    expect(out).toContain('7 proposals couldn’t be read')
    expect(out).toContain('bad-4.json')
    expect(out).not.toContain('bad-5.json')
    expect(out).toContain('…and 2 more.')
    expect(html(<ProposalsView state={list([], problems.slice(0, 1))} api={api} />)).toContain('1 proposal couldn’t be read and is not shown')
  })

  it('done items say what happened, with a link for a ticket', () => {
    const done = [{ ...P, status: { state: 'ticketed', ticket: 777 } }, { ...P, id: 'b', status: { state: 'dismissed', reason: 'nah' } }]
    const out = html(<ProposalsView state={list([])} api={api} done={done} />)
    expect(out).toContain('Made ticket #777')
    expect(out).toContain('https://github.com/G-Eskayo/marvin/issues/777')
    expect(out).toContain('Dismissed: nah')
  })

  it('an action error says nothing was changed', () => {
    const out = html(<ProposalCard proposal={P} api={api} onDone={() => {}} initialUi={{ error: 'gh couldn’t create the ticket: HTTP 502' }} />)
    expect(out).toContain('gh couldn’t create the ticket: HTTP 502 Nothing was changed.')
  })

  it('menus list their choices', () => {
    expect(html(<ProposalCard proposal={P} api={api} onDone={() => {}} initialUi={{ menu: 'snooze' }} />)).toMatch(/1 week.*1 month.*3 months/)
    expect(html(<ProposalCard proposal={P} api={api} onDone={() => {}} initialUi={{ menu: 'dismiss' }} />)).toMatch(/Dismiss with reason….*Dismiss until…/)
  })

  it('dismiss-until dialog defaults the bring-back date 90 days out', () => {
    const out = html(<DismissUntil proposal={P} onSubmit={() => {}} onCancel={() => {}} today={new Date('2026-10-15T12:00:00')} />)
    expect(out).toContain('value="2027-01-13"')
    expect(out).toContain('A ticket is done')
    expect(out).toContain('Something exists')
  })

  it('dismiss-reason dialog', () => {
    const out = html(<DismissReason proposal={P} onSubmit={() => {}} onCancel={() => {}} error="proposal x isn't open" />)
    expect(out).toContain('Dismiss with reason')
    expect(out).toContain('proposal x isn&#x27;t open')
  })
})

describe('MR Review toggle', () => {
  it('has Proposals with its count', () => {
    expect(html(<ViewToggle view="open" setView={() => {}} openCount={2} proposalCount={3} />)).toContain('Proposals (3)')
    expect(html(<ViewToggle view="open" setView={() => {}} openCount={2} />)).toMatch(/>Proposals</)
  })
})
