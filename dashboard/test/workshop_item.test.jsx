import { describe, it, expect, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { itemTarget, targetKey, resolveItem, lifeStages, currentStage, historyRows, barText, barWho, pinnedSha, LIFE } from '../src/lib/workshop_item.js'
import WorkshopItem from '../src/components/WorkshopItem.jsx'
import WorkshopTab from '../src/components/WorkshopTab.jsx'

// #863 (ADR 0063: these try to break it). One page for a ticket and its PRs, from either link; every existing rule
// (Approve waits for the Decisions, failing checks, conflicts, the merge queue) is the old control's, moved.
const NOW = Date.parse('2026-11-03T12:00:00Z')
const ago = (min) => new Date(NOW - min * 60_000).toISOString()
const REPO = 'acme/app'
const SHA = 'a1c9f04aa1c9f04aa1c9f04aa1c9f04aa1c9f04a'

const decisions = (pending = ['workers', 'idle', 'third']) => ({
  present: true, problems: [], pending,
  questions: [
    { id: 'workers', question: 'workers: Where do sub-agents sit on the map?', kind: 'single', required: true, options: [{ label: 'Under their project', checked: false }, { label: 'Under the Mac running them', checked: false }] },
    { id: 'idle', question: 'idle: How do idle parts look?', kind: 'single', required: true, options: [{ label: 'Still and dim', checked: false }, { label: 'Hidden', checked: false }] },
    { id: 'third', question: 'third: A third?', kind: 'single', required: true, options: [{ label: 'Yes', checked: false }, { label: 'No', checked: false }] }
  ]
})
const pr = (number, extra = {}) => ({ number, title: `PR ${number}`, url: `https://github.com/${REPO}/pull/${number}`, repo: REPO, key: `${REPO}#${number}`,
  createdAt: ago(60), headRefOid: 'f'.repeat(40), checks: { state: 'passing', failing: [], pending: [] }, decisions: { present: false, pending: [], problems: [] },
  ticketRef: null, mergeQueue: null, images: [], canMerge: true, ...extra })
const ticket = (number, labels = [], extra = {}) => ({ repo: REPO, number, title: `Ticket ${number}`, labels, createdAt: ago(300), updatedAt: ago(5), column: 'backlog', reason: '', prs: [], ...extra })
const feedOf = (value, extra = {}) => ({ value: { prs: [], tickets: [], projects: [{ id: 'app', repo: REPO }], running: [], queue: [], proposals: [], machines: { 'mac-mini-1': 'Mac mini' }, ...value }, events: new Map(), at: NOW, failed: [], loaded: true, reload: () => {}, ...extra })

beforeEach(() => {
  const never = () => new Promise(() => {})
  globalThis.window = { api: { relations: { pr: never, ticket: never }, mr: { mergeState: never, image: never, historyDetail: never, onMergeEvent: () => () => {} }, boards: { ticket: never }, activity: { timeline: never }, decisions: {} } }
})

const page = (target, feed, initial = {}) => renderToStaticMarkup(<WorkshopItem target={target} feed={feed} now={NOW} initial={{ rel: { docs: [], tickets: [], prs: [] }, ...initial }} />)
const count = (html, re) => (html.match(re) || []).length
const approveButtons = (html) => count(html, />Approve<\/button>/g)

describe('itemTarget: what a link asks for (junk never opens a page)', () => {
  it('reads repo + pr or ticket, numbers as numbers', () => {
    expect(itemTarget({ item: { repo: REPO, pr: 5 } })).toEqual({ repo: REPO, pr: 5 })
    expect(itemTarget({ item: { repo: REPO, ticket: '12' } })).toEqual({ repo: REPO, ticket: 12 })
  })
  it('rejects a missing repo, a bare name, zero, negatives, NaN and objects', () => {
    for (const bad of [null, {}, { item: null }, { item: { pr: 5 } }, { item: { repo: 'app', pr: 5 } }, { item: { repo: REPO } }, { item: { repo: REPO, pr: 0 } },
      { item: { repo: REPO, pr: -3 } }, { item: { repo: REPO, pr: NaN } }, { item: { repo: REPO, ticket: '1e3' } }, { item: { repo: REPO, pr: { n: 1 } } }]) {
      expect(itemTarget(bad), JSON.stringify(bad)).toBeNull()
    }
  })
  it('a PR link and a ticket link to the same work are different targets but the same page', () => {
    const value = feedOf({ prs: [pr(856, { ticketRef: 854 })], tickets: [ticket(854, [], { column: 'review', prs: [856] })] }).value
    const a = resolveItem({ repo: REPO, pr: 856 }, value, NOW)
    const b = resolveItem({ repo: REPO, ticket: 854 }, value, NOW)
    expect(targetKey(a.target)).not.toBe(targetKey(b.target))
    expect([a.ticketNumber, a.pr.number, a.step.verb]).toEqual([b.ticketNumber, b.pr.number, b.step.verb])
  })
})

describe('resolveItem: the break-it list', () => {
  it('a ticket with no PR: the ticket leads, with its own next step', () => {
    const r = resolveItem({ repo: REPO, ticket: 7 }, feedOf({ tickets: [ticket(7, ['needs-info'])] }).value, NOW)
    expect(r.pr).toBeNull()
    expect(r.prs).toEqual([])
    expect(r.step.verb).toBe('Give info')
    expect(barWho(r.step).label).toBe('Your move')
  })
  it('a PR with no ticket: the PR leads, no ticket number, no ticket guessed', () => {
    const r = resolveItem({ repo: REPO, pr: 9 }, feedOf({ prs: [pr(9)], tickets: [ticket(1)] }).value, NOW)
    expect(r.ticketNumber).toBeNull()
    expect(r.ticket).toBeNull()
    expect(r.step.verb).toBe('Approve')
  })
  it('a ticket with two PRs: the one whose move is yours leads; from either PR, that PR leads and lists the other', () => {
    const value = feedOf({ prs: [pr(20, { ticketRef: 5, checks: { state: 'pending', failing: [], pending: ['ci'] } }), pr(21, { ticketRef: 5 })], tickets: [ticket(5, [], { column: 'review', prs: [20, 21] })] }).value
    const fromTicket = resolveItem({ repo: REPO, ticket: 5 }, value, NOW)
    expect(fromTicket.pr.number).toBe(21)
    expect(fromTicket.others.map((p) => p.number)).toEqual([20])
    const from20 = resolveItem({ repo: REPO, pr: 20 }, value, NOW)
    expect(from20.pr.number).toBe(20)
    expect(from20.others.map((p) => p.number)).toEqual([21])
    expect(from20.step.verb).toBe('Checks running')
  })
  it('two PRs, neither yours: the lowest number leads', () => {
    const busy = { checks: { state: 'pending', failing: [], pending: ['ci'] } }
    const value = feedOf({ prs: [pr(31, { ticketRef: 5, ...busy }), pr(30, { ticketRef: 5, ...busy })], tickets: [ticket(5)] }).value
    expect(resolveItem({ repo: REPO, ticket: 5 }, value, NOW).pr.number).toBe(30)
  })
  it('a closed PR whose ticket is still open: the PR is read on its own, and the ticket\'s step leads the bar', () => {
    const value = feedOf({ prs: [], tickets: [ticket(5, ['ready-for-agent'], { column: 'ready', prs: [40] })] }).value
    const r = resolveItem({ repo: REPO, pr: 40 }, value, NOW)
    expect(r.closedPr).toBe(40)
    expect(r.pr).toBeNull()
    expect(r.ticketNumber).toBe(5)
    expect(r.step.verb).toBe('Ready')
  })
  it('a PR of another repo with the same number is never picked', () => {
    const value = feedOf({ prs: [{ ...pr(9), repo: 'acme/other', key: 'acme/other#9' }] }).value
    const r = resolveItem({ repo: REPO, pr: 9 }, value, NOW)
    expect(r.pr).toBeNull()
    expect(r.closedPr).toBe(9)
  })
  it('an empty or broken feed resolves without throwing', () => {
    expect(resolveItem({ repo: REPO, ticket: 1 }, {}, NOW).ticket).toBeNull()
    expect(resolveItem({ repo: REPO, pr: 1 }, { prs: null, tickets: 'x' }, NOW).closedPr).toBe(1)
    expect(resolveItem(null, {}, NOW)).toBeNull()
  })
})

describe('the life strip: Ticket → Look → Your answer → Build → Review → Merge → Shipped', () => {
  const stageOf = (target, value) => {
    const r = resolveItem(target, value, NOW)
    return currentStage({ step: r.step, pr: r.pr })
  }
  it('has the seven stages of the plan, in order', () => {
    expect(LIFE.map(([, l]) => l)).toEqual(['Ticket', 'Look', 'Your answer', 'Build', 'Review', 'Merge', 'Shipped'])
  })
  it('a look with decisions to answer lights Your answer, the stages before it are done, the rest to come', () => {
    const value = feedOf({ prs: [pr(856, { title: 'Mock-up: map', mockups: [{}], decisions: decisions() })] }).value
    const r = resolveItem({ repo: REPO, pr: 856 }, value, NOW)
    const s = lifeStages({ step: r.step, pr: r.pr })
    expect(s.map((x) => x.state)).toEqual(['done', 'done', 'now', 'later', 'later', 'later', 'later'])
    expect(s[2].tone).toBe('yours')
  })
  it('each state lands on its stage', () => {
    expect(stageOf({ repo: REPO, pr: 1 }, feedOf({ prs: [pr(1, { mergeQueue: { queued: true, state: 'queued', reason: '2nd' } })] }).value)).toBe('merge')
    expect(stageOf({ repo: REPO, pr: 1 }, feedOf({ prs: [pr(1, { checks: { state: 'failing', failing: ['ci'], pending: [] } })] }).value)).toBe('build')
    expect(stageOf({ repo: REPO, pr: 1 }, feedOf({ prs: [pr(1)] }).value)).toBe('review')
    expect(stageOf({ repo: REPO, pr: 1 }, feedOf({ prs: [pr(1, { mockups: [{}], checks: { state: 'pending', failing: [], pending: ['ci'] } })] }).value)).toBe('look')
    expect(stageOf({ repo: REPO, ticket: 3 }, feedOf({ tickets: [ticket(3, ['claimed:mac-mini-1'], { column: 'progress', updatedAt: ago(1) })] }).value)).toBe('build')
    expect(stageOf({ repo: REPO, ticket: 3 }, feedOf({ tickets: [ticket(3, ['ready-for-agent'], { column: 'ready' })] }).value)).toBe('ticket')
    expect(currentStage({ step: null, pr: null, closedPrState: 'MERGED' })).toBe('shipped')
    expect(currentStage({ step: null, pr: null, ticketState: 'CLOSED' })).toBe('shipped')
  })
  it('shipped: every stage that happened is done, none lit in a move colour', () => {
    const s = lifeStages({ step: null, pr: null, seen: { state: 'MERGED', mockups: [{}], decisions: { present: true } }, closedPrState: 'MERGED' })
    expect(s.slice(0, 6).every((x) => x.state === 'done')).toBe(true)
    expect(s[6]).toMatchObject({ state: 'now', tone: 'done' })
  })
  it('a stage that never happened is skipped, never drawn as done (no look, no Decisions)', () => {
    const merged = lifeStages({ step: null, pr: null, seen: { state: 'MERGED', decisions: { present: false } }, closedPrState: 'MERGED' })
    expect(merged.map((x) => x.state)).toEqual(['done', 'skipped', 'skipped', 'done', 'done', 'done', 'now'])
    const r = resolveItem({ repo: REPO, ticket: 7 }, feedOf({ tickets: [ticket(7, ['needs-info'])] }).value, NOW)
    expect(lifeStages({ step: r.step, pr: null }).map((x) => x.state)).toEqual(['done', 'skipped', 'now', 'later', 'later', 'later', 'later'])
    const review = resolveItem({ repo: REPO, pr: 1 }, feedOf({ prs: [pr(1, { decisions: { present: true, pending: [], problems: [], questions: [] } })] }).value, NOW)
    expect(lifeStages({ step: review.step, pr: review.pr }).map((x) => x.state)).toEqual(['done', 'skipped', 'done', 'done', 'now', 'later', 'later'])
  })
})

describe('the bar and the history', () => {
  it('"Answer 3 decisions, then approve" only when an approve follows', () => {
    expect(barText({ verb: 'Answer 3 decisions' }, { canMerge: true })).toBe('Answer 3 decisions, then approve')
    expect(barText({ verb: 'Answer 1 decision' }, { canMerge: false })).toBe('Answer 1 decision')
    expect(barText({ verb: 'Answer 1 decision' }, null)).toBe('Answer 1 decision')
    expect(barText({ verb: 'Approve' }, { canMerge: true })).toBe('Approve')
  })
  it('history: newest first, the Mac by its display name, how long each stage took, cost, then Ticket opened', () => {
    const rows = historyRows([
      { stage: 'claimed', status: 'running', timestamp: '2026-11-03T05:02:00Z', machine: 'macbook-pro' },
      { stage: 'executing', status: 'passed', timestamp: '2026-11-03T05:24:00Z', machine: 'mac-mini-1', cost_usd: 0.41 }
    ], { machines: { 'mac-mini-1': 'Mac mini' }, ticketCreatedAt: '2026-11-03T04:51:00Z' })
    expect(rows.map((r) => r.text)).toEqual(['Build · Mac mini · 22 min · $0.41', 'Claimed running · macbook-pro', 'Ticket opened'])
    expect(rows[0].at).toBeGreaterThan(rows[1].at)
  })
  it('history survives junk events and a missing ticket time', () => {
    expect(historyRows([null, { stage: 'x' }, { stage: 'gate', status: 'failed', timestamp: 'nope' }], {})).toEqual([])
    expect(historyRows(undefined)).toEqual([])
  })
  it('pinned to one full commit, else nothing', () => {
    expect(pinnedSha([{ url: `https://raw.githubusercontent.com/a/b/${SHA}/x.png` }, { url: `https://raw.githubusercontent.com/a/b/${SHA}/y.png` }])).toBe('a1c9f04')
    expect(pinnedSha([{ url: `https://raw.githubusercontent.com/a/b/${SHA}/x.png` }, { url: 'https://raw.githubusercontent.com/a/b/main/y.png' }])).toBeNull()
    expect(pinnedSha([])).toBeNull()
  })
})

describe('WorkshopItem: the old controls, moved, with their rules', () => {
  const lookFeed = () => feedOf({ prs: [pr(856, { title: 'Mock-up: Body and Work halves', ticketRef: 854, mockups: [{}], decisions: decisions(),
    images: [{ url: `https://raw.githubusercontent.com/${REPO}/${SHA}/a.png`, alt: '1440 px', kind: 'image' }] })], tickets: [ticket(854, [], { title: 'Map mock-up: Body and Work halves', column: 'review', prs: [856] })] })

  it('decisions pending: the bar says your move, Submit decisions, and Approve stays disabled', () => {
    const h = page({ repo: REPO, pr: 856 }, lookFeed())
    expect(h).toContain('Your move')
    expect(h).toContain('Answer 3 decisions, then approve')
    expect(h).toContain('Submit decisions')
    expect(approveButtons(h)).toBe(1)
    expect(h).toMatch(/<button[^>]*disabled=""[^>]*>Approve<\/button>/)
    expect(h).toContain('Answer the decisions first')
    expect(h).toContain('pinned to a1c9f04')
    expect(h).toMatch(/data-stage="answer" data-state="now" aria-current="step"/)
  })
  it('the page reads in the mock-up\'s order: bar, title, strip, images, Decisions, ticket, history, Related', () => {
    const h = page({ repo: REPO, pr: 856 }, lookFeed(), { ticket: { number: 854, title: 'Map mock-up', body: 'The ticket body.', labels: [], state: 'OPEN', comments: [] } })
    const at = ['data-testid="next-step-bar"', 'data-testid="item-title"', 'data-testid="life-strip"', 'data-testid="item-images"', 'data-testid="item-decisions"',
      'data-testid="item-ticket"', 'data-testid="item-history"', 'data-testid="item-related"'].map((m) => h.indexOf(m))
    expect(at.every((i) => i > -1)).toBe(true)
    expect([...at].sort((a, b) => a - b)).toEqual(at)
    expect(h).toContain('Map mock-up: Body and Work halves')
    expect(h).toContain('ticket #854')
    expect(h).toContain('PR #856')
  })
  it('from the ticket link, the very same page (same PR, same controls)', () => {
    const a = page({ repo: REPO, pr: 856 }, lookFeed())
    const b = page({ repo: REPO, ticket: 854 }, lookFeed())
    const item = (h) => /data-item="([^"]*)"/.exec(h)[1]
    expect(item(a)).toBe(item(b))
    expect(approveButtons(b)).toBe(1)
  })
  it('Approve pressed twice: there is only ever one Approve on the page, and in the merge queue there is none', () => {
    const queued = feedOf({ prs: [pr(5, { mergeQueue: { queued: true, state: 'queued', reason: '1st in the queue' } })] })
    const h = page({ repo: REPO, pr: 5 }, queued)
    expect(approveButtons(h)).toBe(0)
    expect(h).toContain('Approved: in the merge queue')
    expect(h).toContain('MARVIN is on it')
    expect(approveButtons(page({ repo: REPO, pr: 5 }, feedOf({ prs: [pr(5)] })))).toBe(1)
  })
  it('failing checks and conflicts keep their own words and hide Approve', () => {
    const failing = page({ repo: REPO, pr: 5 }, feedOf({ prs: [pr(5, { checks: { state: 'failing', failing: ['ci'], pending: [] } })] }))
    expect(failing).toContain('GitHub checks failed')
    expect(approveButtons(failing)).toBe(0)
    const conflict = page({ repo: REPO, pr: 5 }, feedOf({ prs: [pr(5, { conflicts: true })] }))
    expect(conflict).toContain('Conflicts with main')
    expect(approveButtons(conflict)).toBe(0)
  })
  it('a refused Approve (#678) shows the refusal; the PR\'s card decides Approve again', () => {
    const h = page({ repo: REPO, pr: 5 }, feedOf({ prs: [pr(5, { refusal: { at: ago(10), reason: 'CI_FAILED', message: 'ci failed' } })] }))
    expect(h).toContain('data-refusal="1"')
    expect(h).toContain('CI_FAILED')
    expect(approveButtons(h)).toBe(1)
  })
  it('a ticket with no PR: its reply box and history, no Approve, and its own Decisions are answered here', () => {
    const body = '## Decisions\n<!-- marvin:decisions -->\n### a: Pick one\n- [ ] One\n- [ ] Two\n'
    const h = page({ repo: REPO, ticket: 7 }, feedOf({ tickets: [ticket(7, ['needs-info'])] }), {
      ticket: { number: 7, title: 'Ticket 7', body, labels: [{ name: 'needs-info' }], state: 'OPEN', comments: [] },
      events: [{ stage: 'claimed', status: 'passed', timestamp: ago(30), machine: 'mac-mini-1' }]
    })
    expect(approveButtons(h)).toBe(0)
    expect(h).toContain('Give info')
    expect(h).toContain('data-testid="item-decisions"')
    expect(h).toContain('Pick one')
    expect(h).toContain('Reply')
    expect(h).toContain('Claimed · Mac mini')
    expect(h).toMatch(/data-stage="answer" data-state="now"/)
  })
  it('a PR with no ticket says so, and has no ticket card', () => {
    const h = page({ repo: REPO, pr: 9 }, feedOf({ prs: [pr(9)] }))
    expect(h).toContain('no ticket')
    expect(h).not.toContain('data-testid="item-ticket"')
  })
  it('a ticket with two PRs: the other is one tap away', () => {
    const value = { prs: [pr(20, { ticketRef: 5 }), pr(21, { ticketRef: 5 })], tickets: [ticket(5, [], { prs: [20, 21] })] }
    const h = page({ repo: REPO, ticket: 5 }, feedOf(value))
    expect(h).toContain('data-other-pr="21"')
    expect(approveButtons(h)).toBe(1)
  })
  it('a merged PR read from history: read-only, Shipped lit, no Approve', () => {
    const merged = { ...pr(40), state: 'MERGED', mergedAt: ago(30), readOnly: true, canMerge: false }
    const h = page({ repo: REPO, pr: 40 }, feedOf({}), { closedPr: merged })
    expect(h).toContain('read-only')
    expect(approveButtons(h)).toBe(0)
    expect(h).toMatch(/data-stage="shipped" data-state="now"/)
  })
  it('a closed (not merged) PR with its ticket still open: the ticket\'s step leads, the PR is read-only', () => {
    const closed = { ...pr(40), state: 'CLOSED', readOnly: true, canMerge: false }
    const h = page({ repo: REPO, pr: 40 }, feedOf({ tickets: [ticket(5, ['ready-for-agent'], { column: 'ready', prs: [40] })] }), { closedPr: closed })
    expect(h).toContain('Up next')
    expect(h).toContain('closed · read-only')
    expect(approveButtons(h)).toBe(0)
    expect(h).toMatch(/data-stage="ticket" data-state="now"/)
  })
  it('saved (slim) PR data: says the images are being read rather than "needs images"', () => {
    const slim = pr(5)
    delete slim.images
    const h = page({ repo: REPO, pr: 5 }, feedOf({ prs: [slim] }))
    expect(h).toContain('data-testid="images-loading"')
  })
  it('a 300-character title wraps; no fixed width wider than 860 px', () => {
    const long = 'x'.repeat(300)
    const h = page({ repo: REPO, ticket: 7 }, feedOf({ tickets: [ticket(7, ['needs-info'], { title: long })] }))
    expect(h).toContain(long)
    expect(h).toMatch(/data-testid="item-title"[^>]*|class="[^"]*overflow-wrap:anywhere[^"]*"[^>]*data-testid="item-title"/)
    expect(h).not.toMatch(/(?<![-\w])min-w-\[\d|(?<![-\w])w-\[(?:9|1\d)\d\dpx\]/)
  })
})

describe('deep links: the right item on the first frame, never a flash of Now', () => {
  it('a navigation naming an item renders the item page straight away', () => {
    const feed = feedOf({ prs: [pr(856, { ticketRef: 854 })], tickets: [ticket(854)] })
    const h = renderToStaticMarkup(<WorkshopTab feed={feed} navigate={() => {}} nav={{ tab: 'workshop', item: { repo: REPO, pr: 856 }, at: 1 }} />)
    expect(h).toContain('data-testid="workshop-item"')
    expect(h).not.toContain('data-testid="now-yours"')
    expect(h).toContain('PR #856')
  })
  it('before the feed has loaded: the item page says Loading, not Now and not another item', () => {
    const h = renderToStaticMarkup(<WorkshopTab feed={{ value: null, events: new Map(), loaded: false, failed: [] }} navigate={() => {}} nav={{ tab: 'workshop', item: { repo: REPO, ticket: 3 }, at: 2 }} />)
    expect(h).toContain('data-testid="item-loading"')
    expect(h).not.toContain('data-testid="now-yours"')
  })
  it('a navigation to another tab, or a junk item, leaves the Workshop on Now', () => {
    const feed = feedOf({})
    for (const nav of [{ tab: 'docs', item: { repo: REPO, pr: 1 }, at: 3 }, { tab: 'workshop', item: { repo: 'nope', pr: 1 }, at: 4 }, null]) {
      const h = renderToStaticMarkup(<WorkshopTab feed={feed} navigate={() => {}} nav={nav} />)
      expect(h, JSON.stringify(nav)).toContain('data-testid="workshop"')
      expect(h, JSON.stringify(nav)).not.toContain('data-testid="workshop-item"')
    }
  })
})
