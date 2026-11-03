import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'fs'
import { createRelationsService } from '../electron/main/relations_service.js'

const issue = (n, over = {}) => ({ number: n, title: `T${n}`, state: 'OPEN', labels: [], body: '', url: `u${n}`, createdAt: '2026-10-01T00:00:00Z', ...over })
const projects = [{ id: 'marvin', repo: 'G-Eskayo/marvin' }]
const docs = [
  { project: 'marvin', path: 'CONTEXT.md', label: 'CONTEXT.md', content: 'tracked in #2' },
  { project: 'marvin', path: 'docs/adr/0033-health.md', label: '0033-health.md', content: '# h' }
]
const make = (over = {}) =>
  createRelationsService({
    getRepos: () => ['G-Eskayo/marvin'],
    getBoardData: async () => ({ issues: [issue(1, { body: 'per ADR 0033, blocked by #2' }), issue(2, { labels: [{ name: 'ready-for-agent' }] })], prs: [] }),
    getDocs: async () => docs,
    getProjects: () => projects,
    ...over
  })

describe('relations service', () => {
  it('answers for a ticket with the docs it names and the state of related tickets (board column included)', async () => {
    const r = await make().forTicket('G-Eskayo/marvin', 1)
    expect(r.docs.map((d) => d.path)).toEqual(['docs/adr/0033-health.md'])
    expect(r.tickets[0]).toMatchObject({ number: 2, relation: 'blocked by', column: 'ready' })
  })

  it('answers for a doc with the tickets that mention it', async () => {
    const r = await make().forDoc('marvin', 'docs/adr/0033-health.md')
    expect(r.tickets.map((t) => t.number)).toEqual([1])
  })

  it('caches the build until invalidated', async () => {
    const getBoardData = vi.fn(async () => ({ issues: [issue(1)], prs: [] }))
    const s = make({ getBoardData })
    await s.forTicket('G-Eskayo/marvin', 1)
    await s.forTicket('G-Eskayo/marvin', 1)
    expect(getBoardData).toHaveBeenCalledTimes(1)
    s.invalidate()
    await s.forTicket('G-Eskayo/marvin', 1)
    expect(getBoardData).toHaveBeenCalledTimes(2)
  })

  it('one repo failing to load does not take the rest down', async () => {
    const getBoardData = async (repo) => {
      if (repo === 'o/bad') throw new Error('404')
      return { issues: [issue(1)], prs: [] }
    }
    const s = make({ getRepos: () => ['o/bad', 'G-Eskayo/marvin'], getBoardData })
    expect((await s.forTicket('G-Eskayo/marvin', 1)).docs).toEqual([])
  })

  it('gives linkify its context: the project\'s repo and which file each ADR number is', async () => {
    const c = await make().context('marvin')
    expect(c).toEqual({ project: 'marvin', repo: 'G-Eskayo/marvin', adrs: { 33: 'docs/adr/0033-health.md' } })
    expect(await make().context('unknown')).toEqual({ project: 'unknown', repo: null, adrs: {} })
  })
})

describe('review parity (MR Review <-> board)', () => {
  const pr = (n, body, over = {}) => ({ number: n, title: `PR ${n}`, url: `p${n}`, state: 'OPEN', isDraft: false, body, files: [], ...over })
  const svc = (issues, prs) => make({ getBoardData: async () => ({ issues, prs }) })

  it('pairs each open PR with its ticket and the board column that ticket is in', async () => {
    const p = await svc([issue(2, { labels: [{ name: 'ready-for-agent' }] })], [pr(7, 'Closes #2')]).parity()
    expect(p.prs).toHaveLength(1)
    expect(p.prs[0]).toMatchObject({ number: 7, status: 'ok', ticket: { number: 2, title: 'T2', column: 'review' } })
    expect(p.ok).toBe(true)
  })

  it('flags a PR that closes no ticket, so nothing on any board corresponds to it', async () => {
    const p = await svc([issue(2)], [pr(7, 'just a change')]).parity()
    expect(p.prs[0]).toMatchObject({ status: 'no-ticket', ticket: null })
    expect(p.ok).toBe(false)
    expect(p.problems[0]).toMatch(/PR #7/)
  })

  it('shows a denied PR as sent back, matching where the board puts its ticket (not as a mismatch)', async () => {
    const p = await svc([issue(2, { labels: [{ name: 'needs-reengagement' }] })], [pr(7, 'Closes #2')]).parity()
    expect(p.prs[0]).toMatchObject({ status: 'sent-back', ticket: { column: 'blocked' } })
    expect(p.ok).toBe(true)
  })

  it('flags a ticket whose PR is open but which is filed somewhere other than In review', async () => {
    const p = await svc([issue(2, { state: 'CLOSED' })], [pr(7, 'Closes #2')]).parity()
    expect(p.prs[0].status).toBe('elsewhere')
    expect(p.ok).toBe(false)
  })

  it('counts what is waiting on you per project, from the same data', async () => {
    const o = await svc(
      [issue(2), issue(3, { labels: [{ name: 'ready-for-human' }] }), issue(4, { body: 'Blocked by #2' })],
      [pr(7, 'Closes #2')]
    ).overview()
    expect(o['G-Eskayo/marvin']).toMatchObject({ review: 1, needsYou: 1, blocked: 1 })
  })
})

describe('parity does not raise an alarm on a stale snapshot', () => {
  // The ticket's local stage log says verification passed (so the board files it under In review) a moment
  // before its PR exists, or the cached GitHub PR list predates it. Looking again with fresh data shows no problem.
  const raised = { 7: [{ stage: 'verifying', status: 'passed', detail: 'improved', timestamp: '2026-10-05T10:00:00Z' }] }
  const open = issue(7, { labels: [{ name: 'ready-for-agent' }, { name: 'claimed:mac-mini' }] })
  const pr = { number: 70, title: 'Implement #7', url: 'p70', body: 'Closes #7', state: 'OPEN', files: [] }

  function stale() {
    let fresh = false
    const svc = createRelationsService({
      getRepos: () => ['G-Eskayo/marvin'],
      getBoardData: async () => ({ issues: [open], prs: fresh ? [pr] : [] }),
      getDocs: async () => [], getProjects: () => projects, getStages: () => raised,
      recheck: () => { fresh = true }
    })
    return svc
  }

  it('re-reads with fresh data before reporting, and reports nothing if the mismatch was only staleness', async () => {
    const r = await stale().parity()
    expect(r.problems).toEqual([])
    expect(r.ok).toBe(true)
  })

  it('still reports a mismatch that survives a fresh read', async () => {
    const svc = createRelationsService({
      getRepos: () => ['G-Eskayo/marvin'],
      getBoardData: async () => ({ issues: [open], prs: [] }),
      getDocs: async () => [], getProjects: () => projects, getStages: () => raised, recheck: () => {}
    })
    const r = await svc.parity()
    expect(r.problems[0]).toMatch(/Ticket #7 .* is filed under In review but has no open PR/)
  })

  it('does not re-read when there is nothing to double-check', async () => {
    const recheck = vi.fn()
    const svc = createRelationsService({ getRepos: () => ['G-Eskayo/marvin'], getBoardData: async () => ({ issues: [], prs: [] }), getDocs: async () => [], getProjects: () => projects, recheck })
    await svc.parity()
    expect(recheck).not.toHaveBeenCalled()
  })
})

describe('parity recheck does not re-read GitHub on every call (#318 follow-up)', () => {
  const standing = () => {
    let t = 0
    const rechecks = []
    const s = make({
      getBoardData: async () => ({ issues: [issue(2)], prs: [{ number: 7, title: 'p', url: 'p7', body: 'just a change' }] }),
      recheck: (repos) => rechecks.push(repos),
      now: () => t
    })
    return { s, rechecks, tick: (ms) => { t += ms } }
  }

  it('a lasting mismatch is rechecked once, then reported from memory until 5 minutes pass', async () => {
    const { s, rechecks, tick } = standing()
    const first = await s.parity()
    expect(first.ok).toBe(false)
    await s.parity()
    await s.parity()
    expect(rechecks.length).toBe(1)
    tick(5 * 60_000 + 1)
    await s.parity()
    expect(rechecks.length).toBe(2)
  })

  it('rechecks only the repos involved in the mismatch', async () => {
    const { s, rechecks } = standing()
    await s.parity()
    expect(rechecks[0]).toEqual(['G-Eskayo/marvin'])
  })
})

describe('a PR names its ticket as Closes or Part of, in any repo (marvin#1004)', () => {
  const pr = (n, body, over = {}) => ({ number: n, title: `PR ${n}`, url: `p${n}`, state: 'OPEN', isDraft: false, body, files: [], ...over })
  const multi = (byRepo) => make({ getRepos: () => Object.keys(byRepo), getBoardData: async (repo) => byRepo[repo] })

  it('a "Part of" PR satisfies parity, and its ticket is in review', async () => {
    const p = await make({ getBoardData: async () => ({ issues: [issue(2)], prs: [pr(7, 'Mock-up. Part of #2')] }) }).parity()
    expect(p.prs[0]).toMatchObject({ status: 'ok', ticket: { number: 2, column: 'review', relation: 'part of' } })
    expect(p.ok).toBe(true)
  })

  it('"for #2" is still no ticket, and the message says how to name one', async () => {
    const p = await make({ getBoardData: async () => ({ issues: [issue(2)], prs: [pr(7, 'Mock-up for #2')] }) }).parity()
    expect(p.prs[0].status).toBe('no-ticket')
    expect(p.problems[0]).toMatch(/Closes #N.*Part of #N/)
  })

  it('a PR in another repo that closes a ticket puts that ticket in review, with no problem reported', async () => {
    const p = await multi({
      'G-Eskayo/marvin': { issues: [issue(623)], prs: [] },
      'G-Eskayo/marvin-instance': { issues: [], prs: [pr(6, 'Closes G-Eskayo/marvin#623')] }
    }).parity()
    expect(p.prs[0]).toMatchObject({ repo: 'G-Eskayo/marvin-instance', status: 'ok', ticket: { repo: 'G-Eskayo/marvin', number: 623, column: 'review' } })
    expect(p.ok).toBe(true)
  })

  it('a ticket in review whose only PR is in another repo is not "In review but has no open PR"', async () => {
    const p = await multi({
      'G-Eskayo/marvin': { issues: [issue(949)], prs: [] },
      'G-Eskayo/marvin-instance': { issues: [], prs: [pr(9, 'Merge after G-Eskayo/marvin#951. Part of G-Eskayo/marvin#949.')] }
    }).parity()
    expect(p.reviewWithoutPr).toEqual([])
    expect(p.ok).toBe(true)
  })

  it('a ticket named second by a PR (Closes #1, Part of #2) still counts as having an open PR', async () => {
    const p = await make({ getBoardData: async () => ({ issues: [issue(1), issue(2)], prs: [pr(7, 'Closes #1\nPart of #2')] }) }).parity()
    expect(p.prs[0].ticket.number).toBe(1)
    expect(p.reviewWithoutPr).toEqual([])
    expect(p.ok).toBe(true)
  })

  it('the relation index has a part-of edge that is not a closes edge', async () => {
    const s = make({ getBoardData: async () => ({ issues: [issue(2)], prs: [pr(7, 'Part of #2')] }) })
    expect((await s.forPr('G-Eskayo/marvin', 7)).tickets).toEqual([expect.objectContaining({ number: 2, relation: 'part of' })])
    expect((await s.forTicket('G-Eskayo/marvin', 2)).prs).toEqual([expect.objectContaining({ number: 7, relation: 'worked on in' })])
  })

  it('a bare #N in another repo\'s PR is that repo\'s ticket, so no false link to marvin #2', async () => {
    const p = await multi({
      'G-Eskayo/marvin': { issues: [issue(2)], prs: [] },
      'G-Eskayo/clarity-captions': { issues: [], prs: [pr(7, 'Part of #2')] }
    }).parity()
    expect(p.prs[0].status).toBe('no-ticket') // clarity #2 isn't loaded here
    expect((await multi({ 'G-Eskayo/marvin': { issues: [issue(2)], prs: [] }, 'G-Eskayo/clarity-captions': { issues: [], prs: [pr(7, 'Part of #2')] } }).forTicket('G-Eskayo/marvin', 2)).prs).toEqual([])
  })

  it('the six PRs the parity check flagged on 2026-11-02, plus marvin-instance #6, come back clean (recorded fixture)', async () => {
    const { repos } = JSON.parse(readFileSync(new URL('./fixtures/parity_part_of_prs.json', import.meta.url), 'utf-8'))
    const p = await multi(repos).parity()
    expect(p.problems).toEqual([])
    const by = Object.fromEntries(p.prs.map((r) => [r.key, `${r.status} ${r.ticket?.repo}#${r.ticket?.number} ${r.ticket?.column}`]))
    expect(by).toEqual({
      'G-Eskayo/clarity-captions#258': 'ok G-Eskayo/clarity-captions#235 review',
      'G-Eskayo/clarity-captions#255': 'ok G-Eskayo/clarity-captions#246 review',
      'G-Eskayo/clarity-captions#231': 'ok G-Eskayo/clarity-captions#213 review',
      'G-Eskayo/marvin-instance#11': 'sent-back G-Eskayo/marvin#957 blocked',
      'G-Eskayo/marvin-instance#9': 'ok G-Eskayo/marvin#949 review',
      'G-Eskayo/marvin-instance#5': 'ok G-Eskayo/marvin#623 review',
      'G-Eskayo/marvin-instance#6': 'ok G-Eskayo/marvin#623 review'
    })
  })
})
