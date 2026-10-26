import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SupportTab, { groupRequests, stateLabel, outcome, age, splitDiagnostics, Thread, RequestRow, authorLabel, AutoFixSwitch } from '../src/components/SupportTab.jsx'
import ItButton from '../src/components/ItButton.jsx'
import { visibleTabs } from '../src/lib/tabs.js'

const R = (number, state, open = true, extra = {}) => ({ repo: 'helped-person/marvin-support', number, title: `Request ${number}`, state, open, updatedAt: '2026-10-26T00:00:00Z', ...extra })
const noop = { on: () => () => {} }
const api = (state) => ({ state: () => new Promise(() => {}), act: async () => ({ ok: true }), _state: state })

describe('Support tab (ADR 0073)', () => {
  it('needs-you holds only open needs-you requests; everything else is handled', () => {
    const [needsYou, handled] = groupRequests([R(1, 'needs-you'), R(2, 'needs-you', false), R(3, 'answered'), R(4, 'solved-here', false)], 'helper')
    expect(needsYou.items.map((r) => r.number)).toEqual([1])
    expect(handled.items.map((r) => r.number)).toEqual([2, 3, 4])
  })

  it('renders the saved state at once: the waiting request, a collapsed handled count, nothing about other people', () => {
    const html = renderToStaticMarkup(
      <SupportTab api={api()} triggers={noop} now={Date.parse('2026-10-26T02:00:00Z')}
        initial={{ role: 'helper', requests: [R(1, 'needs-you'), R(3, 'answered')], errors: {} }} />
    )
    expect(html).toContain('Needs you (1)')
    expect(html).toContain('Request 1')
    expect(html).toContain('Handled by MARVIN (1)')
    expect(html).not.toContain('Request 3') // collapsed until opened
    expect(html).toContain('2h')
  })

  it('an unreachable repo says so and keeps showing the last saved state', () => {
    const html = renderToStaticMarkup(
      <SupportTab api={api()} triggers={noop} initial={{ role: 'helper', requests: [R(1, 'needs-you')], errors: { 'helped-person/marvin-support': 'offline' } }} />
    )
    expect(html).toContain('Couldn’t reach helped-person/marvin-support')
    expect(html).toContain('Request 1')
  })

  it('labels speak to whoever is looking', () => {
    expect(stateLabel('helper', R(1, 'needs-you'))).toBe('Needs you')
    expect(stateLabel('helped', R(1, 'needs-you'))).toBe('Waiting for your helper')
    expect(stateLabel('helped', R(1, 'answered'))).toBe('Reply waiting')
    expect(stateLabel('helper', R(1, 'answered'))).toBe('… Answered, not applied yet')
  })

  it('a request is fixed only when its check passed on their Mac; closing it is not enough', () => {
    const passed = { check: 'gh auth status', before: { exit: 1 }, after: { exit: 0 }, passed: true }
    const failed = { ...passed, after: { exit: 1 }, passed: false }
    expect(outcome('helper', R(1, 'verified', false, { verification: passed })).text).toBe('✓ Verified on their Mac')
    expect(outcome('helped', R(1, 'verified', false, { verification: passed })).text).toBe('✓ Fixed and verified')
    expect(outcome('helper', R(1, 'answered', false)).text).toBe('Closed, not verified')
    expect(outcome('helper', R(1, 'helper-trying', true, { verification: failed })).text).toBe('↺ Fix failed, back to MARVIN')
    expect(outcome('helper', R(1, 'helper-trying')).text).toBe('Your MARVIN is on it')
  })

  it('the handled list shows each check with its before and after', () => {
    const v = { check: 'gh auth status', before: { exit: 1 }, after: { exit: 0 }, passed: true }
    const html = renderToStaticMarkup(<RequestRow request={R(1, 'verified', false, { verification: v })} role="helper" onSelect={() => {}} />)
    expect(html).toContain('✓ Verified on their Mac')
    expect(html).toContain('gh auth status')
    expect(html).toContain('before: fail (1)')
    expect(html).toContain('after: ok')
  })

  it('the helped side groups into replies waiting, in progress and done', () => {
    const groups = groupRequests([R(1, 'answered'), R(2, 'helper-trying'), R(3, 'verified', false)], 'helped')
    expect(groups.map((g) => [g.title, g.items.map((r) => r.number)])).toEqual([['Replies waiting', [1]], ['In progress', [2]], ['Done', [3]], ['Ideas', []]])
  })

  it('the helped thread offers Apply with MARVIN and a follow-up, not the helper’s reply tools', () => {
    const t = { request: { ...R(1, 'answered'), body: 'x', author: 'helped' }, comments: [{ author: 'helper', body: 'Run gh auth login', check: 'gh auth status' }] }
    const html = renderToStaticMarkup(<Thread thread={t} role="helped" busy={false} draft="" setDraft={() => {}} check="" setCheck={() => {}} />)
    expect(html).toContain('Fix it with MARVIN')
    expect(html).toContain('Send follow-up')
    expect(html).toContain('How we&#x27;ll know it&#x27;s fixed')
    expect(html).not.toContain('Draft with MARVIN')
  })

  it('a verification comment shows whether the check passed on their Mac', () => {
    const v = { check: 'gh auth status', before: { exit: 1, output: 'no' }, after: { exit: 0, output: 'Logged in' }, passed: true }
    const t = { request: { ...R(1, 'verified', false), body: 'x', author: 'helped' }, comments: [{ author: 'helped', body: 'Verified on this Mac.', verification: v }] }
    const html = renderToStaticMarkup(<Thread thread={t} role="helper" busy={false} draft="" setDraft={() => {}} check="" setCheck={() => {}} />)
    expect(html).toContain('✓ Check passed on their Mac')
    expect(html).toContain('Logged in')
    expect(html).not.toContain('Send</button>') // a closed request takes no more replies
    const mine = renderToStaticMarkup(<Thread thread={t} role="helped" busy={false} draft="" setDraft={() => {}} check="" setCheck={() => {}} />)
    expect(mine).toContain('✓ Fixed. Before: not working · After: working')
    expect(mine).toContain('<summary class="cursor-pointer">Details</summary>') // the exit codes are tucked away
  })

  it('age reads minutes, hours and days, and nothing for a bad date', () => {
    const now = Date.parse('2026-10-26T00:00:00Z')
    expect(age('2026-10-25T23:55:00Z', now)).toBe('5m')
    expect(age('2026-10-24T00:00:00Z', now)).toBe('2d')
    expect(age('garbage', now)).toBe('')
  })

  it('shows the diagnostics apart from what the person wrote', () => {
    const body = 'Dashboard blank\n\n<details><summary>Diagnostics (scrubbed)</summary>\n\n```json\n{"version": "0.16.3"}\n```\n</details>\n'
    expect(splitDiagnostics(body)).toEqual({ text: 'Dashboard blank', diagnostics: '{"version": "0.16.3"}' })
    expect(splitDiagnostics('just text')).toEqual({ text: 'just text', diagnostics: null })
    const html = renderToStaticMarkup(
      <Thread thread={{ request: { ...R(1, 'needs-you'), body, author: 'helped' }, comments: [{ author: 'me', body: 'try X' }] }}
        role="helper" busy={false} draft="" setDraft={() => {}} check="" setCheck={() => {}} />
    )
    expect(html).toContain('Draft with MARVIN')
    expect(html).toContain('Diagnostics')
    expect(html).toContain('try X')
  })

  it('the tab exists on both ends of a support link and nowhere else', () => {
    expect(visibleTabs('helper').map((t) => t.id)).toContain('support')
    expect(visibleTabs('helped').map((t) => t.id)).toContain('support')
    expect(visibleTabs(null).map((t) => t.id)).not.toContain('support')
  })
})

describe('IT button (ADR 0073)', () => {
  it('shows a dot when a reply is waiting, and none otherwise', () => {
    const waiting = renderToStaticMarkup(<ItButton api={api()} triggers={noop} initial={{ badge: 1, requests: [] }} />)
    const quiet = renderToStaticMarkup(<ItButton api={api()} triggers={noop} initial={{ badge: 0, requests: [] }} />)
    expect(waiting).toContain('rounded-full bg-blue-500')
    expect(quiet).not.toContain('rounded-full bg-blue-500')
  })

  it('its panel asks what is wrong and lists the person’s requests in their own words', () => {
    const html = renderToStaticMarkup(
      <ItButton api={api()} triggers={noop} initialOpen initial={{ badge: 1, requests: [R(1, 'answered'), R(2, 'helper-trying')] }} />
    )
    expect(html).toContain('What&#x27;s wrong?')
    expect(html).toContain('Get help')
    expect(html).toContain('Reply waiting')
    expect(html).toContain('Sent to your helper&#x27;s MARVIN')
  })
})

describe('ideas (feature, skill and prompt ideas)', () => {
  it('ideas never mix with problems: their own section, never in needs-you or replies waiting', () => {
    const all = [R(1, 'needs-you'), R(2, 'idea-new'), R(3, 'idea-ticket'), R(4, 'answered')]
    const helper = groupRequests(all, 'helper')
    expect(helper.find((g) => g.id === 'needs-you').items.map((r) => r.number)).toEqual([1])
    expect(helper.find((g) => g.id === 'handled').items.map((r) => r.number)).toEqual([4])
    expect(helper.find((g) => g.id === 'ideas').items.map((r) => r.number)).toEqual([2, 3])
    const helped = groupRequests(all, 'helped')
    expect(helped.find((g) => g.id === 'waiting').items.map((r) => r.number)).toEqual([4])
    expect(helped.find((g) => g.id === 'ideas').items.map((r) => r.number)).toEqual([2, 3])
  })

  it('an idea says what happened to it, in each side’s words', () => {
    expect(outcome('helped', R(1, 'idea-ticket')).text).toBe('Made a ticket ✓')
    expect(outcome('helped', R(1, 'idea-shipped', false)).text).toBe('✓ Built')
    expect(outcome('helped', R(1, 'idea-dismissed', false)).text).toBe('Not now')
    expect(outcome('helper', R(1, 'idea-proposal')).text).toBe('In Proposals')
  })

  it('an idea thread offers no fix tools on either side, and says where it is decided', () => {
    const t = { request: { ...R(1, 'idea-proposal'), body: 'A prompt skill', author: 'helped' }, comments: [] }
    const mine = renderToStaticMarkup(<Thread thread={t} role="helped" busy={false} draft="" setDraft={() => {}} check="" setCheck={() => {}} />)
    const theirs = renderToStaticMarkup(<Thread thread={t} role="helper" busy={false} draft="" setDraft={() => {}} check="" setCheck={() => {}} />)
    expect(mine).not.toContain('Fix it with MARVIN')
    expect(theirs).not.toContain('Draft with MARVIN')
    expect(theirs).toContain('MR Review → Proposals')
  })

  it('the IT panel offers both modes and lists ideas apart from requests', () => {
    const html = renderToStaticMarkup(
      <ItButton api={api()} triggers={noop} initialOpen initial={{ badge: 0, requests: [R(1, 'answered'), R(2, 'idea-ticket')] }} />
    )
    expect(html).toContain('Something&#x27;s wrong')
    expect(html).toContain('I have an idea')
    expect(html).toContain('My ideas')
    expect(html).toContain('Made a ticket ✓')
  })
})

describe('written for the person being helped (audience)', () => {
  const t = (comments, state = 'answered') => ({ request: { ...R(1, state), body: 'x', author: 'helped' }, comments })
  const render = (thread, role, extra = {}) => renderToStaticMarkup(<Thread thread={thread} role={role} busy={false} draft="hi" setDraft={() => {}} check="" setCheck={() => {}} {...extra} />)

  it('each comment says who wrote it, in the reader’s words', () => {
    const c = { requester: { by: 'requester', author: 'helped' }, helper: { by: 'helper', author: 'helper-login' }, marvin: { by: 'helper-marvin', author: 'helper-login' } }
    expect([c.requester, c.helper, c.marvin].map((x) => authorLabel('helped', x))).toEqual(['You', 'Your helper', "Your helper's MARVIN (automatic)"])
    expect([c.requester, c.helper, c.marvin].map((x) => authorLabel('helper', x))).toEqual(['helped', 'You', 'Your MARVIN (automatic)'])
  })

  it('the helped side reads what the check means in plain words, with the command tucked away', () => {
    const html = render(t([{ by: 'helper-marvin', author: 'h', body: 'Run one command', check: 'test -s ~/x', check_says: 'your project list exists' }]), 'helped')
    expect(html).toContain('How we&#x27;ll know it&#x27;s fixed: your project list exists')
  })

  it('a failed fix tells the helped person they don’t need to do anything', () => {
    const v = { check: 'test -s ~/x', before: { exit: 1 }, after: { exit: 1 }, passed: false }
    const html = render(t([{ by: 'requester', author: 'helped', body: 'r', verification: v }], 'helper-trying'), 'helped')
    expect(html).toContain('✗ Not fixed yet.')
    expect(html).toContain('You don&#x27;t need to do anything')
    expect(outcome('helped', R(1, 'helper-trying', true, { verification: v })).text).toBe('↺ Not fixed yet, trying again')
  })

  it('the helper previews a rewrite for them before anything is sent, and can still send their own words', () => {
    const before = render(t([], 'needs-you'), 'helper')
    expect(before).toContain('Preview for them')
    expect(before).not.toContain('Send this')
    const during = render(t([], 'needs-you'), 'helper', { preview: true })
    expect(during).toContain('Send this')
    expect(during).toContain('Send as I wrote it')
    expect(during).toContain('Every command is kept exactly as you wrote it')
  })

  it('the helped person’s diagnostics are labelled in plain words', () => {
    const body = 'Blank\n\n<details><summary>Diagnostics (scrubbed)</summary>\n\n```json\n{}\n```\n</details>\n'
    const html = renderToStaticMarkup(<Thread thread={{ request: { ...R(1, 'needs-you'), body, author: 'helped' }, comments: [] }} role="helped" busy={false} draft="" setDraft={() => {}} check="" setCheck={() => {}} />)
    expect(html).toContain('Technical details (sent automatically, no passwords)')
  })
})

describe('headless on the helped Mac (views)', () => {
  const t = (comments, state = 'answered') => ({ request: { ...R(1, state), body: 'x', author: 'helped' }, comments })
  const render = (thread, extra = {}) => renderToStaticMarkup(<Thread thread={thread} role="helped" busy={false} draft="" setDraft={() => {}} check="" setCheck={() => {}} {...extra} />)

  it('an explanation is closed with "Got it, thanks", with nothing to fix', () => {
    const html = render(t([{ by: 'helper-marvin', author: 'h', body: 'Here is what that means', kind: 'explain' }]))
    expect(html).toContain('Got it, thanks')
    expect(html).not.toContain('Fix it with MARVIN')
  })

  it('with automatic fixing on, a fix says MARVIN does it by itself and asks nothing', () => {
    const fix = { by: 'helper-marvin', author: 'h', body: 'Node is missing', kind: 'fix', steps: ['brew install node@24'], check: 'node --version' }
    const auto = render(t([fix]), { autoApply: true })
    expect(auto).toContain('MARVIN will fix this by itself')
    expect(auto).not.toContain('Fix it with MARVIN')
    expect(auto).toContain('What MARVIN will run')
    expect(render(t([fix]), { autoApply: false })).toContain('Fix it with MARVIN')
  })

  it('steps only the person can do are shown plainly, and then nothing runs by itself', () => {
    const fix = { by: 'helper-marvin', author: 'h', body: 'Sign in again', kind: 'fix', steps: ['gh auth status'], you_steps: ['Sign in to GitHub in the browser window'], check: 'gh auth status' }
    const html = render(t([fix]), { autoApply: true })
    expect(html).toContain('What you need to do')
    expect(html).toContain('Sign in to GitHub in the browser window')
    expect(html).not.toContain('MARVIN will fix this by itself')
  })

  it('while the helper’s MARVIN works, the person is told they’ll hear back', () => {
    expect(render(t([], 'helper-trying'))).toContain('You&#x27;ll get a notification')
  })

  it('an answered question reads as answered, on both sides', () => {
    expect(outcome('helped', R(1, 'answered', false, { kind: 'explain' })).text).toBe('✓ Answered')
    expect(outcome('helper', R(1, 'answered', false, { kind: 'explain' })).text).toBe('Explained')
  })

  it('the switch says plainly what it allows', () => {
    const html = renderToStaticMarkup(<AutoFixSwitch on={false} busy={false} onChange={() => {}} />)
    expect(html).toContain('Let MARVIN fix technical problems for me automatically')
    expect(html).toContain('nothing that deletes your files, needs your password or signs you in')
  })
})

describe('the helper’s reply box says what each button does', () => {
  const t = { request: { ...R(1, 'needs-you'), body: 'x', author: 'helped' }, comments: [] }
  const html = renderToStaticMarkup(<Thread thread={t} role="helper" busy={false} draft="note" setDraft={() => {}} check="" setCheck={() => {}} />)
  it('offers a plain send, a preview, and handing it back to MARVIN, each explained', () => {
    for (const label of ['Send to them', 'Preview for them', 'Have MARVIN fix it with this', 'Draft with MARVIN', 'Resolve']) expect(html).toContain(label)
    expect(html).toContain('posts your reply as you wrote it')
    expect(html).toContain('comes back to you if that doesn&#x27;t work')
  })
  it('a note to MARVIN is labelled as one on both sides', () => {
    expect(authorLabel('helper', { by: 'helper', guidance: true })).toBe('You, to your MARVIN')
    expect(authorLabel('helped', { by: 'helper', guidance: true })).toBe("Your helper's note to MARVIN")
  })
})
