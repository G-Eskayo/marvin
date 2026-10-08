import { describe, it, expect } from 'vitest'
import { deriveColumn, buildBoard, COLUMNS, STALE_CLAIM_MS, checklistProgress } from '../electron/main/board.js'

const issue = (over = {}) => ({
  number: 1,
  title: 'Some ticket',
  state: 'OPEN',
  labels: [],
  body: '',
  url: 'https://github.com/o/r/issues/1',
  createdAt: '2026-10-01T00:00:00Z',
  repo: 'o/r',
  ...over
})
const labels = (...names) => names.map((name) => ({ name }))
const pr = (over = {}) => ({
  number: 50,
  title: 'A PR',
  url: 'https://github.com/o/r/pull/50',
  state: 'OPEN',
  isDraft: false,
  body: 'Closes #1',
  repo: 'o/r',
  ...over
})
const ctx = (over = {}) => ({
  prs: [],
  events: [],
  isLive: false,
  openNumbers: new Set([1]),
  heldNumbers: new Set(),
  notPlannedNumbers: new Set(),
  ...over
})

describe('deriveColumn', () => {
  it('puts closed issues in done', () => {
    expect(deriveColumn(issue({ state: 'CLOSED' }), ctx()).column).toBe('done')
  })

  it('puts a ticket with an open closing PR in review, linking the PR', () => {
    const r = deriveColumn(issue(), ctx({ prs: [pr()] }))
    expect(r.column).toBe('review')
    expect(r.prs.map((p) => p.number)).toEqual([50])
  })

  it('ignores PRs that are merged/closed or close other tickets', () => {
    expect(deriveColumn(issue(), ctx({ prs: [pr({ state: 'MERGED' })] })).column).toBe('backlog')
    expect(deriveColumn(issue(), ctx({ prs: [pr({ body: 'Closes #2' })] })).column).toBe('backlog')
  })

  it('treats a verifying/gate/merging last stage as review even without a PR', () => {
    const events = [{ stage: 'verifying', status: 'started' }]
    expect(deriveColumn(issue(), ctx({ events })).column).toBe('review')
  })

  it('blocks on the blocked label with a reason', () => {
    const r = deriveColumn(issue({ labels: labels('blocked') }), ctx())
    expect(r.column).toBe('blocked')
    expect(r.reason).toMatch(/blocked/i)
  })

  it('blocks on an open "Blocked by #n" dependency, naming it', () => {
    const r = deriveColumn(issue({ body: 'Blocked by #7' }), ctx({ openNumbers: new Set([1, 7]) }))
    expect(r.column).toBe('blocked')
    expect(r.reason).toContain('#7')
  })

  it('reads the to-issues "## Blocked by" section, ignoring "None"', () => {
    const open = ctx({ openNumbers: new Set([1, 12]) })
    const sec = (t) => issue({ body: `## What to build\nx\n\n## Blocked by\n\n${t}\n\n## Notes\nsee #12` })
    expect(deriveColumn(sec('- #12 the schema'), open).reason).toContain('#12')
    expect(deriveColumn(sec('None - can start immediately'), open).column).toBe('backlog')
  })

  it('does not block when the dependency is already closed', () => {
    const r = deriveColumn(issue({ body: 'Blocked by #7', labels: labels('ready-for-agent') }), ctx())
    expect(r.column).toBe('ready')
  })

  it('blocks when the pipeline failed and nothing is running', () => {
    const events = [
      { stage: 'executing', status: 'started' },
      { stage: 'executing', status: 'failed', detail: 'tests red' }
    ]
    const r = deriveColumn(issue({ labels: labels('claimed:mac-mini') }), ctx({ events }))
    expect(r.column).toBe('blocked')
    expect(r.reason).toContain('executing')
  })

  it('keeps a failed-but-live ticket in progress (a retry is running)', () => {
    const events = [{ stage: 'executing', status: 'failed' }]
    const r = deriveColumn(issue({ labels: labels('claimed:mac-mini') }), ctx({ events, isLive: true }))
    expect(r.column).toBe('progress')
  })

  it('puts claimed tickets in progress, naming the machine', () => {
    const r = deriveColumn(issue({ labels: labels('claimed:mac-mini') }), ctx())
    expect(r.column).toBe('progress')
    expect(r.reason).toContain('mac-mini')
  })

  it('puts unclaimed ready tickets in ready, flagging human-only ones', () => {
    expect(deriveColumn(issue({ labels: labels('ready-for-agent') }), ctx())).toMatchObject({ column: 'ready', owner: 'agent' })
    expect(deriveColumn(issue({ labels: labels('ready-for-human') }), ctx())).toMatchObject({ column: 'ready', owner: 'human' })
  })

  it('puts everything else open in backlog, explaining needs-info', () => {
    expect(deriveColumn(issue(), ctx()).column).toBe('backlog')
    expect(deriveColumn(issue({ labels: labels('needs-info') }), ctx()).reason).toMatch(/info/i)
  })

  it('notes dev-environment evidence on the PR', () => {
    const body = 'Closes #1\n## Metrics Comparison\nx\n## Test Results\ny\n## Dev Environment Evidence\nz'
    const r = deriveColumn(issue(), ctx({ prs: [pr({ body })] }))
    expect(r.prs[0].hasDevEvidence).toBe(true)
  })
})

describe('buildBoard', () => {
  it('groups cards into every column (empty ones included) with titles attached', () => {
    const issues = [
      issue({ number: 1, title: 'One', labels: labels('ready-for-agent') }),
      issue({ number: 2, title: 'Two', state: 'CLOSED' }),
      issue({ number: 3, title: 'Three', body: 'Blocked by #1' })
    ]
    const board = buildBoard({ repo: 'o/r', issues, prs: [], eventsByNumber: {}, liveNumbers: new Set() })
    expect(board.columns.map((c) => c.id)).toEqual(COLUMNS.map((c) => c.id))
    const byId = Object.fromEntries(board.columns.map((c) => [c.id, c.cards.map((x) => x.number)]))
    expect(byId).toMatchObject({ ready: [1], done: [2], blocked: [3], backlog: [], progress: [], review: [] })
    expect(board.columns.flatMap((c) => c.cards).every((c) => c.title)).toBe(true)
  })
})

import { summarizeBoard } from '../electron/main/board.js'
import { projectIdOf } from '../src/lib/projects.js'

describe('summarizeBoard / projectIdOf', () => {
  it('counts cards per column and lists what needs attention', () => {
    const board = buildBoard({
      repo: 'o/r',
      issues: [
        issue({ number: 1, labels: labels('ready-for-agent') }),
        issue({ number: 2, labels: labels('ready-for-agent'), createdAt: '2026-10-02T00:00:00Z' }),
        issue({ number: 3, body: 'Blocked by #1' }),
        issue({ number: 4, state: 'CLOSED' })
      ],
      prs: [],
      eventsByNumber: {},
      liveNumbers: new Set()
    })
    const s = summarizeBoard(board)
    expect(s.counts).toMatchObject({ ready: 2, blocked: 1, done: 1, progress: 0, review: 0, backlog: 0 })
    expect(s.open).toBe(3)
    expect(s.total).toBe(4)
  })

  it('derives the same project id as the Python catalog', () => {
    expect(projectIdOf('G-Eskayo/Portfolio_Website')).toBe('portfolio-website')
    expect(projectIdOf('G-Eskayo/marvin')).toBe('marvin')
    expect(projectIdOf('G-Eskayo/ML_supervised_learning-Regression-Classification-project')).toBe('ml-supervised-learning-regression-classification-project')
  })
})


describe('stale claims', () => {
  const NOW = Date.parse('2026-10-05T12:00:00Z')
  const iso = (msAgo) => new Date(NOW - msAgo).toISOString()
  const claimed = (updatedMsAgo) => issue({ labels: labels('claimed:mac-mini'), updatedAt: iso(updatedMsAgo) })

  it('a claim nobody has touched for over a day is not "in progress": it is blocked, saying so', () => {
    const r = deriveColumn(claimed(3 * 24 * 3600_000), ctx({ now: NOW }))
    expect(r.column).toBe('blocked')
    expect(r.reason).toMatch(/mac-mini/)
    expect(r.reason).toMatch(/3 days/)
  })

  it('a recently touched claim stays in progress', () => {
    expect(deriveColumn(claimed(2 * 3600_000), ctx({ now: NOW })).column).toBe('progress')
  })

  it('a live dispatch or a recent pipeline stage keeps an old-looking claim in progress', () => {
    expect(deriveColumn(claimed(5 * 24 * 3600_000), ctx({ now: NOW, isLive: true })).column).toBe('progress')
    const events = [{ stage: 'executing', status: 'started', timestamp: iso(60_000) }]
    expect(deriveColumn(claimed(5 * 24 * 3600_000), ctx({ now: NOW, events })).column).toBe('progress')
  })

  it('without an updatedAt there is no basis to call a claim stale', () => {
    expect(deriveColumn(issue({ labels: labels('claimed:mac-mini') }), ctx({ now: NOW })).column).toBe('progress')
  })

  it('exposes the threshold (one day)', () => {
    expect(STALE_CLAIM_MS).toBe(24 * 3600_000)
  })
})

import { ARCHIVE_AFTER_DAYS, labelKind } from '../electron/main/board.js'

describe('tags on cards', () => {
  const NOW = Date.parse('2026-10-05T12:00:00Z')
  const board = (issues) => buildBoard({ repo: 'o/r', issues, prs: [], eventsByNumber: {}, liveNumbers: new Set(), now: NOW })
  const card = (b, n) => b.columns.flatMap((c) => [...c.cards, ...(c.archive || [])]).find((k) => k.number === n)

  it('classifies labels into type, state, claim, priority and other', () => {
    expect(labelKind('bug')).toBe('type')
    expect(labelKind('research-spike')).toBe('type')
    expect(labelKind('ready-for-agent')).toBe('state')
    expect(labelKind('needs-reengagement')).toBe('state')
    expect(labelKind('claimed:mac-mini')).toBe('claim')
    expect(labelKind('priority:p1')).toBe('priority')
    expect(labelKind('area:dashboard')).toBe('other')
  })

  it('gives each card its tags (with kinds), who holds the claim, and what blocks it', () => {
    const b = board([
      issue({ number: 7, labels: labels('bug', 'ready-for-agent', 'priority:p1', 'area:docs') }),
      issue({ number: 8, labels: labels('claimed:mac-mini'), updatedAt: new Date(NOW - 3600_000).toISOString() }),
      issue({ number: 9, body: '## Blocked by\n\n- #7' })
    ])
    expect(card(b, 7).tags.map((t) => [t.name, t.kind])).toEqual([['bug', 'type'], ['ready-for-agent', 'state'], ['priority:p1', 'priority'], ['area:docs', 'other']])
    expect(card(b, 8).claimedBy).toBe('mac-mini')
    expect(card(b, 9).blockedBy).toEqual([7])
  })

  it('carries age in days from creation', () => {
    const b = board([issue({ number: 7, createdAt: new Date(NOW - 5 * 86400_000).toISOString() })])
    expect(card(b, 7).ageDays).toBe(5)
  })
})

describe('archive', () => {
  const NOW = Date.parse('2026-10-05T12:00:00Z')
  const closed = (n, daysAgo) => issue({ number: n, state: 'CLOSED', closedAt: new Date(NOW - daysAgo * 86400_000).toISOString() })
  const done = (issues) => buildBoard({ repo: 'o/r', issues, prs: [], eventsByNumber: {}, liveNumbers: new Set(), now: NOW }).columns.find((c) => c.id === 'done')

  it('keeps recently closed tickets in Done, newest first, and moves older ones to the archive', () => {
    const d = done([closed(1, 20), closed(2, 3), closed(3, 1), closed(4, 400)])
    expect(d.cards.map((c) => c.number)).toEqual([3, 2])
    expect(d.archive.map((c) => c.number)).toEqual([1, 4])
  })

  it('has a 14 day window, and a closed ticket with no date stays visible rather than vanishing', () => {
    expect(ARCHIVE_AFTER_DAYS).toBe(14)
    const d = done([issue({ number: 5, state: 'CLOSED' })])
    expect(d.cards.map((c) => c.number)).toEqual([5])
  })

  it('summarizeBoard reports the archive separately and does not count it as open or recent', () => {
    const b = buildBoard({ repo: 'o/r', issues: [closed(1, 20), closed(2, 1)], prs: [], now: NOW })
    const s = summarizeBoard(b)
    expect(s.counts.done).toBe(1)
    expect(s.archived).toBe(1)
  })
})

import { buildCompleted } from '../electron/main/board.js'

describe('buildCompleted', () => {
  const closedIssue = (n, createdDaysAgo, closedDaysAgo, extra = {}) => ({
    number: n,
    title: `T${n}`,
    state: 'CLOSED',
    labels: [{ name: 'enhancement' }],
    url: `u${n}`,
    createdAt: new Date(Date.parse('2026-10-05T12:00:00Z') - createdDaysAgo * 86400_000).toISOString(),
    closedAt: new Date(Date.parse('2026-10-05T12:00:00Z') - closedDaysAgo * 86400_000).toISOString(),
    ...extra
  })

  it('lists closed tickets newest first with how long each took, grouped by month', () => {
    const out = buildCompleted({ issues: [closedIssue(1, 40, 35), closedIssue(2, 5, 1), closedIssue(3, 20, 18)], prs: [] })
    expect(out.items.map((i) => i.number)).toEqual([2, 3, 1])
    expect(out.items[0].tookDays).toBe(4)
    // closed 1, 18 and 35 days before 2026-10-05: Oct, Sep, Aug
    expect(out.months.map((m) => [m.month, m.items.length])).toEqual([['2026-10', 1], ['2026-09', 1], ['2026-08', 1]])
  })

  it('ignores open tickets', () => {
    const open = { ...closedIssue(9, 3, 1), state: 'OPEN', closedAt: null }
    expect(buildCompleted({ issues: [open], prs: [] }).items).toEqual([])
  })

  it('names the merged PR that closed each ticket, from its "Closes #n"', () => {
    const prs = [{ number: 50, title: 'The fix', url: 'p50', body: 'Closes #2', mergedAt: '2026-10-04T00:00:00Z' }]
    const out = buildCompleted({ issues: [closedIssue(2, 5, 1)], prs })
    expect(out.items[0].pr).toMatchObject({ number: 50, title: 'The fix' })
  })

  it('keeps the tags so completed work can be filtered the same way as the board', () => {
    const out = buildCompleted({ issues: [closedIssue(1, 5, 1, { labels: [{ name: 'bug' }, { name: 'claimed:mac-mini' }] })], prs: [] })
    expect(out.items[0].tags.map((t) => [t.name, t.kind])).toEqual([['bug', 'type'], ['claimed:mac-mini', 'claim']])
  })
})

describe('a denied PR (sent back for rework)', () => {
  it('moves the ticket out of "In review": the PR is still open but the ball is back with the agent', () => {
    const r = deriveColumn(issue({ labels: labels('needs-reengagement') }), ctx({ prs: [pr()] }))
    expect(r.column).toBe('blocked')
    expect(r.reason).toMatch(/sent back/i)
    expect(r.reason).toContain('PR #50')
    expect(r.prs.map((p) => p.number)).toEqual([50]) // the PR stays attached, so the board can still link to it
  })

  it('does not change a PR that is simply awaiting review', () => {
    expect(deriveColumn(issue({ labels: labels('ready-for-agent') }), ctx({ prs: [pr()] })).column).toBe('review')
  })

  it('a needs-reengagement ticket with no open PR is not "sent back from review" (nothing to review)', () => {
    expect(deriveColumn(issue({ labels: labels('needs-reengagement') }), ctx()).reason).not.toMatch(/sent back from review/i)
  })
})

describe('existing-work evidence on cards', () => {
  const NOW2 = Date.parse('2026-10-05T12:00:00Z')
  const iss = (n) => ({ number: n, title: 't' + n, state: 'OPEN', labels: [{ name: 'ready-for-agent' }], createdAt: '2026-10-01T00:00:00Z', url: 'u' })
  const build = (evidenceByNumber) => buildBoard({ repo: 'o/r', issues: [iss(1), iss(2)], prs: [], now: NOW2, evidenceByNumber })
  const cards = (b) => b.columns.flatMap((c) => c.cards)

  it('attaches the verdict and evidence to the matching card only', () => {
    const ev = { 1: { verdict: 'looks-done', evidence: [{ kind: 'commit', ref: 'abc1234', detail: 'Add thing (#1)' }] } }
    const [a, b] = cards(build(ev)).sort((x, y) => x.number - y.number)
    expect(a.evidence).toEqual({ verdict: 'looks-done', items: ev[1].evidence })
    expect(b.evidence).toBeNull()
  })

  it('works with no evidence supplied (older callers)', () => {
    expect(cards(buildBoard({ repo: 'o/r', issues: [iss(1)], prs: [], now: NOW2 }))[0].evidence).toBeNull()
  })

  it('a ready ticket with existing work says so in its reason, so the column is not a lie', () => {
    const ev = { 1: { verdict: 'in-flight', evidence: [{ kind: 'rescue-ref', ref: 'refs/rescue/x', detail: 'a prior run' }] } }
    const c = cards(build(ev)).find((x) => x.number === 1)
    expect(c.reason).toMatch(/work already exists/i)
  })
})

import { getEvidence, clearEvidenceCache } from '../electron/main/boards.js'
describe('getEvidence', () => {
  it('caches per repo, and a failing check means no evidence rather than a broken board', async () => {
    clearEvidenceCache()
    let calls = 0
    const ok = async () => { calls++; return '{"3":{"verdict":"in-flight","evidence":[]}}' }
    expect(await getEvidence('o/a', { run: ok, now: 1000 })).toEqual({ 3: { verdict: 'in-flight', evidence: [] } })
    await getEvidence('o/a', { run: ok, now: 2000 })
    expect(calls).toBe(1)
    expect(await getEvidence('o/b', { run: async () => { throw new Error('boom') }, now: 1000 })).toEqual({})
  })
})

// marvin #139: a ticket can be decided about ("on hold", "not planned") and partly finished, and the board must say so.
describe('on hold and not planned (marvin #139)', () => {
  const dependsOn1 = (over = {}) => issue({ number: 2, body: '## Blocked by\n\n- #1 The other ticket\n', labels: labels('ready-for-agent'), ...over })

  it('a held ticket sits in the backlog and says it is on hold', () => {
    const r = deriveColumn(issue({ labels: labels('ready-for-agent', 'hold') }), ctx())
    expect(r).toMatchObject({ column: 'backlog', held: true })
    expect(r.reason).toMatch(/on hold/i)
  })

  it('a held ticket does not count as a blocker, and the dependent ticket says so', () => {
    const r = deriveColumn(dependsOn1(), ctx({ openNumbers: new Set([1, 2]), heldNumbers: new Set([1]) }))
    expect(r.column).toBe('ready')
    expect(r.reason).toMatch(/#1/)
    expect(r.reason).toMatch(/on hold/i)
  })

  it('is still blocked by a different open ticket, and mentions the held one it ignores', () => {
    const t = issue({ number: 3, labels: labels('ready-for-agent'), body: '## Blocked by\n\n- #1 a\n- #2 b\n' })
    const r = deriveColumn(t, ctx({ openNumbers: new Set([1, 2, 3]), heldNumbers: new Set([1]) }))
    expect(r.column).toBe('blocked')
    expect(r.reason).toMatch(/Blocked by #2/)
    expect(r.reason).toMatch(/#1.*on hold/i)
  })

  it('a dependency closed as not planned is not a blocker, and the dependent says so', () => {
    const r = deriveColumn(dependsOn1(), ctx({ openNumbers: new Set([2]), notPlannedNumbers: new Set([1]) }))
    expect(r.column).toBe('ready')
    expect(r.reason).toMatch(/#1.*not planned/i)
  })

  it('a still-open ticket with no hold behaves exactly as before', () => {
    expect(deriveColumn(dependsOn1(), ctx({ openNumbers: new Set([1, 2]) })).column).toBe('blocked')
  })

  it('buildBoard works the held and not-planned sets out from the issues themselves', () => {
    const issues = [
      issue({ number: 1, labels: labels('hold') }),
      issue({ number: 2, labels: labels('ready-for-agent'), body: '## Blocked by\n\n- #1 held one\n' }),
      issue({ number: 3, state: 'CLOSED', stateReason: 'NOT_PLANNED', closedAt: '2026-10-05T00:00:00Z' }),
      issue({ number: 4, labels: labels('ready-for-agent'), body: '## Blocked by\n\n- #3 dropped one\n' })
    ]
    const board = buildBoard({ repo: 'o/r', issues, prs: [] })
    const cardOf = (n) => board.columns.flatMap((c) => c.cards).find((c) => c.number === n)
    expect(cardOf(1).held).toBe(true)
    expect(cardOf(2).blockedBy).toEqual([])
    expect(cardOf(2).heldDependencies).toEqual([1])
    expect(cardOf(4).blockedBy).toEqual([])
    expect(board.columns.find((c) => c.id === 'ready').cards.map((c) => c.number).sort()).toEqual([2, 4])
  })
})

describe('partial progress on a card (marvin #139)', () => {
  it('counts ticked and unticked checklist items in the acceptance criteria', () => {
    expect(checklistProgress('## What\n\n- [x] not criteria\n\n## Acceptance criteria\n\n- [x] a\n- [ ] b\n- [X] c\n\n## Blocked by\n\n- [ ] ignore')).toEqual({ done: 2, total: 3 })
  })

  it('falls back to the whole body when there is no acceptance-criteria section', () => {
    expect(checklistProgress('- [x] one\n- [ ] two')).toEqual({ done: 1, total: 2 })
  })

  it('is null when there is no checklist', () => {
    expect(checklistProgress('Just words.')).toBe(null)
    expect(checklistProgress('')).toBe(null)
    expect(checklistProgress(undefined)).toBe(null)
  })

  it('shows up on the card', () => {
    const board = buildBoard({ repo: 'o/r', issues: [issue({ body: '## Acceptance criteria\n\n- [x] a\n- [ ] b\n' })], prs: [] })
    expect(board.columns.flatMap((c) => c.cards)[0].progress).toEqual({ done: 1, total: 2 })
  })
})


