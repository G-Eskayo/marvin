import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { buildNow, nextStep, prStep, ticketStep, SECTIONS, MARVIN_STUCK_MS, projectChip } from '../src/lib/next_step.js'
import { readSources, loadSaved, save, SAVED_KEY } from '../src/lib/workshop_feed.js'
import { WorkshopNow } from '../src/components/WorkshopTab.jsx'

// #862 (ADR 0063: these try to break it). Every open ticket, PR and proposal lands in exactly one section; the Now
// view survives 0 and 200 items, a 300-character title, a project with no catalog id, GitHub unreachable, and 860 px.
const NOW = Date.parse('2026-11-02T12:00:00Z')
const ago = (min) => new Date(NOW - min * 60_000).toISOString()
const REPO = 'acme/app'
const OTHER = 'acme/uncatalogued'
const projects = [{ id: 'app', repo: REPO }]

const pr = (number, extra = {}) => ({ number, title: `PR ${number}`, url: `https://github.com/${REPO}/pull/${number}`, repo: REPO, key: `${REPO}#${number}`,
  createdAt: ago(60), checks: { state: 'passing', failing: [], pending: [] }, decisions: { pending: [], problems: [] }, ticketRef: null, mergeQueue: null, ...extra })
const ticket = (number, labels = [], extra = {}) => ({ repo: REPO, number, title: `Ticket ${number}`, labels, createdAt: ago(120), updatedAt: ago(5), column: 'backlog', reason: '', prs: [], ...extra })

// A mixed snapshot touching every branch of nextStep.
function snapshot() {
  const tickets = [
    ticket(1, ['needs-info', 'priority:p3']),
    ticket(2, ['ready-for-human', 'p1']),
    ticket(3, ['ready-for-agent', 'priority:p1'], { column: 'ready' }),
    ticket(4, ['ready-for-agent'], { column: 'ready' }),
    ticket(5, ['claimed:builder-1'], { column: 'progress' }),
    ticket(6, ['claimed:builder-1'], { column: 'blocked', reason: 'Claimed by builder-1 but no activity for 3 days' }),
    ticket(7, [], { column: 'blocked', reason: 'Pipeline failed at executing: boom' }),
    ticket(8, ['hold'], { column: 'backlog', reason: 'On hold' }),
    ticket(9, [], { column: 'blocked', reason: 'Blocked by #1, still open' }),
    ticket(10, ['needs-triage']),
    ticket(11, ['priority:p2'], { column: 'review', reason: 'PR #50 open', prs: [50] }), // its PR carries it
    ticket(12, ['owner-decisions']),
    ticket(13, ['needs-reengagement'], { column: 'blocked', reason: 'Sent back from review: waiting for rework (PR #51 still open)', prs: [51] }),
    { ...ticket(14, ['needs-info']), repo: OTHER }
  ]
  const prs = [
    pr(50, { ticketRef: 11 }),
    pr(51, { ticketRef: 13, sentBack: true }),
    pr(52, { decisions: { pending: ['a', 'b', 'c'], problems: [] } }),
    pr(53, { checks: { state: 'pending', failing: [], pending: ['ci'], runs: [{ state: 'success' }, { state: 'pending' }] } }),
    pr(54, { mergeQueue: { queued: true, state: 'queued', reason: '2nd in the queue' } }),
    pr(55, { conflicts: true, mergeQueue: { reason: 'conflicts with main · needs a rebuild', conflict: true } }),
    pr(56, { mergeQueue: { state: 'waiting', reason: "your answers aren't built yet", unbuilt: true } }),
    pr(57, { mockups: [{}] })
  ]
  const running = [{ repo: REPO, number: 5, title: 'Ticket 5', machine: 'builder-1' }]
  const queue = [{ position: 1, repo: REPO, number: 3, title: 'Ticket 3', priority: 'p1' }, { position: 2, repo: REPO, number: 4, title: 'Ticket 4' },
    { position: 3, repo: OTHER, number: 99, title: 'Only in the queue' }]
  const proposals = [{ id: 'p-1', title: 'A proposal', added: '2026-11-01' }]
  const events = new Map([[`${REPO}#5`, [{ stage: 'claimed', status: 'running', timestamp: ago(18) }, { stage: 'executing', status: 'running', timestamp: ago(2) }]]])
  return { prs, tickets, projects, running, queue, proposals, events }
}

function expectCoverage(src, now) {
  const { items, sections } = buildNow(src, now)
  // Every ticket (itself or through the PR that closes it), PR and proposal exactly once, in exactly one section.
  const seen = new Map()
  for (const s of SECTIONS) for (const i of sections[s]) {
    const keys = i.type === 'ticket' ? [i.key] : [i.key, ...i.covers]
    for (const k of keys) seen.set(k, (seen.get(k) || 0) + 1)
  }
  const want = [...src.tickets.map((t) => `${t.repo}#${t.number}`), ...src.prs.map((p) => p.key), ...src.proposals.map((p) => `proposal:${p.id}`),
    ...[...src.running, ...src.queue].map((r) => `${r.repo}#${r.number}`)]
  for (const k of new Set(want)) expect(seen.get(k), k).toBe(1)
  expect(SECTIONS.reduce((n, s) => n + sections[s].length, 0)).toBe(items.length)
  return sections
}

describe('nextStep (#862, the Now view\'s slice of #860)', () => {
  it('every open ticket, PR and proposal is in exactly one section: none dropped, none twice', () => {
    const s = expectCoverage(snapshot(), NOW)
    const verbs = (sec) => s[sec].map((i) => `${i.key}:${i.step.verb}`)
    expect(verbs('yours')).toEqual(expect.arrayContaining([`${REPO}#1:Give info`, `${REPO}#2:Your task`, `${REPO}#52:Answer 3 decisions`, `${REPO}#50:Approve`, `${REPO}#57:Approve the look`, 'proposal:p-1:Weigh a proposal']))
    expect(verbs('marvin')).toEqual(expect.arrayContaining([`${REPO}#5:Building`, `${REPO}#53:Checks running`, `${REPO}#54:In the merge queue`, `${REPO}#56:Building your answers`, `${REPO}#51:Sent back`]))
    expect(verbs('stuck')).toEqual(expect.arrayContaining([`${REPO}#6:No movement`, `${REPO}#7:Build failed`, `${REPO}#12:Act on your answers`, `${REPO}#55:Needs a rebuild`]))
    expect(s.next.map((i) => i.key)).toEqual([`${REPO}#3`, `${REPO}#4`, `${OTHER}#99`])
    expect(s.next[0].step.verb).toBe('Next')
    expect(s.waiting.map((i) => i.step.verb).sort()).toEqual(['Blocked', 'Needs triage', 'On hold'])
  })

  it('a ticket its PR closes is carried by the PR, and the PR takes its priority', () => {
    const { items } = buildNow(snapshot(), NOW)
    expect(items.find((i) => i.key === `${REPO}#11`)).toBeUndefined()
    const host = items.find((i) => i.key === `${REPO}#50`)
    expect(host.covers).toEqual([`${REPO}#11`])
    expect(host.priority).toBe('p2')
  })

  it('Your move: p1 to p3, then the oldest wait first; unprioritised last', () => {
    const src = { tickets: [ticket(1, ['needs-info', 'p3'], { createdAt: ago(10) }), ticket(2, ['needs-info'], { createdAt: ago(999) }),
      ticket(3, ['needs-info', 'p1'], { createdAt: ago(5) }), ticket(4, ['needs-info', 'p3'], { createdAt: ago(50) })] }
    expect(buildNow(src, NOW).sections.yours.map((i) => i.number)).toEqual([3, 4, 1, 2])
  })

  it('MARVIN\'s step with no movement past 30 min is Stuck, not "on it" (I5)', () => {
    const t = ticket(5, ['claimed:x'], { column: 'progress' })
    const events = (min) => new Map([[`${REPO}#5`, [{ stage: 'executing', status: 'running', timestamp: ago(min) }]]])
    expect(ticketStep(t, { events: events(29), now: NOW }).section).toBe('marvin')
    const stuck = ticketStep(t, { events: events(31), now: NOW })
    expect(stuck.section).toBe('stuck')
    expect(NOW - stuck.stuckSince).toBeGreaterThan(MARVIN_STUCK_MS)
  })

  it('unknown labels, both needs-info and ready-for-agent, a bare item: still one answer each', () => {
    expect(ticketStep(ticket(1, ['weird', 'needs-info', 'ready-for-agent'])).section).toBe('yours')
    expect(ticketStep({ repo: REPO, number: 2 }).section).toBe('waiting')
    expect(prStep({ repo: REPO, number: 3 }).owner).toBe('owner')
    expect(nextStep({ type: 'mystery' }).section).toBe('waiting')
  })

  it('a project with no catalog id shows its repo name as the chip', () => {
    expect(projectChip(OTHER, projects)).toBe('uncatalogued')
    expect(projectChip(REPO, projects)).toBe('app')
    expect(projectChip(REPO, null)).toBe('app')
  })

  it('0 items and 200 items', () => {
    const empty = buildNow({}, NOW)
    expect(empty.items).toEqual([])
    expect(empty.count).toBe(0)
    const big = { tickets: Array.from({ length: 120 }, (_, i) => ticket(i + 1, i % 2 ? ['needs-info'] : ['ready-for-agent'], { column: i % 2 ? 'backlog' : 'ready' })),
      prs: Array.from({ length: 80 }, (_, i) => pr(1000 + i)), proposals: [], running: [], queue: [], projects }
    const s = expectCoverage(big, NOW)
    expect(s.yours.length + s.next.length).toBe(200)
  })
})

const feedOf = (src, extra = {}) => ({ now: buildNow(src, NOW), failed: [], loaded: true, at: NOW, ...extra })
const render = (feed) => renderToStaticMarkup(<WorkshopNow feed={feed} onOpen={() => {}} now={NOW} />)

describe('the Now view (#862)', () => {
  it('sections in order, Stuck only when not empty, every shown item once', () => {
    const src = snapshot()
    const h = render(feedOf(src))
    const order = ['now-stuck', 'now-yours', 'now-marvin', 'now-next'].map((id) => h.indexOf(`data-testid="${id}"`))
    expect(order.every((i) => i >= 0)).toBe(true)
    expect([...order].sort((a, b) => a - b)).toEqual(order)
    const { sections } = buildNow(src, NOW)
    const rows = (h.match(/data-testid="now-row"/g) || []).length
    // Up next shows its first row with "N more ready"; "MARVIN is on it" is never collapsed.
    expect(rows).toBe(sections.stuck.length + sections.yours.length + sections.marvin.length + 1)
    expect(h).toContain(`▸ ${sections.next.length - 1} more ready`)
    expect(h).toContain(`all ${sections.marvin.length} · everything in motion`)
    expect(render(feedOf({ tickets: [ticket(1, ['needs-info'])] }))).not.toContain('now-stuck')
  })

  it('rows start with the verb; an in-motion row has its worker, elapsed time and stage strip', () => {
    const h = render(feedOf(snapshot()))
    expect(h).toMatch(/>Answer 3 decisions</)
    expect(h).toMatch(/builder-1 · 18 min/)
    expect(h).toContain('aria-label="stages"')
    expect(h).toMatch(/>Stuck [^<]* · MARVIN</)
  })

  it('0 items says nothing waiting only when the data is fresh', () => {
    expect(render(feedOf({}))).toContain('Nothing waiting on you.')
  })

  it('a 300-character title wraps rather than being clipped or pushing the page wide', () => {
    const long = 'x'.repeat(300)
    const h = render(feedOf({ tickets: [ticket(1, ['needs-info'], { title: long })] }))
    expect(h).toContain(long)
    expect(h).toMatch(/class="[^"]*min-w-0[^"]*"/)
    expect(h).toContain('[overflow-wrap:anywhere]')
    expect(h).not.toMatch(/\btruncate\b/)
  })

  it('GitHub unreachable: the last known list with "as of", never an empty "nothing waiting"', async () => {
    const down = () => Promise.reject(new Error('getaddrinfo ENOTFOUND api.github.com'))
    const api = { mr: { list: down }, activity: { openTickets: down }, queue: { list: () => Promise.resolve({ queue: [], running: [], error: 'gh failed' }) }, proposals: { list: down } }
    const prev = { prs: [], tickets: [ticket(1, ['needs-info'])], projects, running: [], queue: [], proposals: [] }
    const { value, failed } = await readSources(api, prev)
    expect(failed).toEqual(['pull requests', 'tickets', 'the ticket queue', 'proposals'])
    expect(value.tickets).toHaveLength(1)
    const h = render(feedOf(value, { failed, at: NOW - 3600_000 }))
    expect(h).toContain('data-testid="as-of"')
    expect(h).toMatch(/as of /)
    expect(h).toContain('Ticket 1')
    expect(h).not.toContain('Nothing waiting on you.')
    // Never read and nothing saved: an error, not an empty list.
    const none = render({ now: null, failed: ['tickets'], loaded: true, at: null })
    expect(none).toMatch(/Can’t reach GitHub/)
    expect(none).not.toContain('Nothing waiting')
  })

  it('the saved copy round-trips (with events) and survives junk in storage', () => {
    const mem = new Map()
    const storage = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) }
    const src = snapshot()
    save(storage, src, src.events, NOW)
    const back = loadSaved(storage)
    expect(back.at).toBe(NOW)
    expect(back.value.tickets).toHaveLength(src.tickets.length)
    expect(back.events.get(`${REPO}#5`)).toHaveLength(2)
    mem.set(SAVED_KEY, JSON.stringify({ at: 1, value: { tickets: 'nope', events: 7 } }))
    expect(loadSaved(storage).value.tickets).toEqual([])
    const throwing = { getItem: () => { throw new Error('denied') }, setItem: () => { throw new Error('full') } }
    expect(loadSaved(throwing)).toBeNull()
    expect(() => save(throwing, src)).not.toThrow()
  })

  it('860 px: rows stack below lg, so nothing needs horizontal scroll', () => {
    const h = render(feedOf(snapshot()))
    const row = h.match(/<button[^>]*data-testid="now-row"[^>]*class="([^"]*)"|<button[^>]*class="([^"]*)"[^>]*data-testid="now-row"/)
    const cls = (row[1] || row[2]).split(' ')
    expect(cls).toEqual(expect.arrayContaining(['flex-col', 'lg:flex-row', 'min-w-0', 'w-full']))
    expect(h).not.toMatch(/\bmin-w-\[\d|\bw-\[(?:9|1\d)\d\dpx\]/)
  })
})

describe('nextStep follows the pipeline\'s queue (#862, found on real data)', () => {
  it('a ticket whose last run failed but is back in the ready queue is Up next, not Stuck', () => {
    const t = ticket(7, ['ready-for-agent'], { column: 'blocked', reason: 'Pipeline failed at executing: boom' })
    expect(ticketStep(t, { queued: new Map([[`${REPO}#7`, 1]]) })).toMatchObject({ section: 'next', verb: 'Next' })
    expect(ticketStep(t, {}).section).toBe('stuck')
  })
  it('a PR with failing checks says why, not "sent back"', () => {
    const p = pr(60, { checks: { state: 'failing', failing: ['ci'], pending: [] }, mergeQueue: { reason: 'checks failing: ci' } })
    const h = render(feedOf({ prs: [p] }))
    expect(h).toContain('checks failing: ci')
    expect(h).not.toContain('sent back')
  })
})

describe('a queue that lists a ticket twice (seen on real data, 2026-11-02)', () => {
  it('shows it once, at its first place', () => {
    const queue = [{ position: 1, repo: REPO, number: 3, title: 'T3' }, { position: 2, repo: REPO, number: 3, title: 'T3' }, { position: 3, repo: REPO, number: 4, title: 'T4' }]
    const src = { tickets: [ticket(3, ['ready-for-agent'], { column: 'ready' })], queue, prs: [], proposals: [], running: [] }
    const s = expectCoverage(src, NOW)
    expect(s.next.map((i) => [i.number, i.step.verb])).toEqual([[3, 'Next'], [4, 'Ready']])
  })
})

describe('a PR\'s own blockers in the merge queue\'s order (seen on real data)', () => {
  it('Decisions waiting beat a conflict: the owner\'s move, and the line doesn\'t repeat the verb', () => {
    const p = pr(70, { conflicts: true, decisions: { pending: ['a', 'b'], problems: [] }, mergeQueue: { reason: '2 Decisions are waiting for you' } })
    expect(prStep(p)).toMatchObject({ owner: 'owner', verb: 'Answer 2 decisions', section: 'yours' })
    const h = render(feedOf({ prs: [p] }))
    expect(h).not.toContain('waiting for you<')
    expect(h).not.toContain('2 Decisions are waiting')
  })
  it('unbuilt answers beat failing checks', () => {
    const p = pr(71, { checks: { state: 'failing', failing: ['ci'], pending: [] }, mergeQueue: { reason: "your answers aren't built yet", unbuilt: true } })
    expect(prStep(p)).toMatchObject({ owner: 'marvin', verb: 'Building your answers' })
  })
  it('at 860 px the right label sits at the row\'s right edge (the middle column spans the row)', () => {
    const h = render(feedOf(snapshot()))
    expect(h).toMatch(/class="flex w-full min-w-0 flex-1 items-center gap-4 lg:w-auto"/)
  })
})
