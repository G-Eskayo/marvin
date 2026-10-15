import { describe, it, expect, vi } from 'vitest'
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

  describe('overview() with rankNeedsYou per repo', () => {
    it('test 1: computes needsYou count from rankNeedsYou with ready-for-human label', async () => {
      const tickets = [
        issue(1, { labels: [{ name: 'ready-for-human' }] }),
        issue(2, { labels: [{ name: 'ready-for-human' }] }),
        issue(3, { labels: [{ name: 'needs-info' }] })
      ]
      const o = await svc(tickets, []).overview()
      expect(o['G-Eskayo/marvin'].needsYou).toBe(3)
    })

    it('test 2: ignores tickets with hold or pinned labels', async () => {
      const tickets = [
        issue(1, { labels: [{ name: 'ready-for-human' }] }),
        issue(2, { labels: [{ name: 'ready-for-human' }, { name: 'hold' }] }),
        issue(3, { labels: [{ name: 'ready-for-human' }, { name: 'pinned' }] })
      ]
      const o = await svc(tickets, []).overview()
      expect(o['G-Eskayo/marvin'].needsYou).toBe(1)
    })

    it('test 3: counts review (via PR closing reference) and blocked separately from needsYou', async () => {
      const tickets = [
        issue(1, { labels: [{ name: 'ready-for-human' }] }),
        issue(2, { labels: [{ name: 'blocked' }] })
      ]
      const prs = [pr(7, 'Closes #1')]
      const o = await svc(tickets, prs).overview()
      expect(o['G-Eskayo/marvin']).toMatchObject({ review: 1, needsYou: 1, blocked: 1 })
    })

    it('test 4: groups counts by repo correctly', async () => {
      const marvinTickets = [
        issue(1, { labels: [{ name: 'ready-for-human' }] })
      ]
      const financeTickets = [
        { number: 10, title: 'T10', state: 'OPEN', labels: [{ name: 'ready-for-human' }], body: '', url: 'u10', createdAt: '2026-10-01T00:00:00Z', repo: 'G-Eskayo/finance-os' }
      ]
      const s = createRelationsService({
        getRepos: () => ['G-Eskayo/marvin', 'G-Eskayo/finance-os'],
        getBoardData: async (repo) => {
          if (repo === 'G-Eskayo/marvin') return { issues: marvinTickets, prs: [] }
          if (repo === 'G-Eskayo/finance-os') return { issues: financeTickets, prs: [] }
          return { issues: [], prs: [] }
        },
        getDocs: async () => [],
        getProjects: () => [
          { id: 'marvin', repo: 'G-Eskayo/marvin' },
          { id: 'finance-os', repo: 'G-Eskayo/finance-os' }
        ]
      })
      const o = await s.overview()
      expect(o['G-Eskayo/marvin'].needsYou).toBe(1)
      expect(o['G-Eskayo/finance-os'].needsYou).toBe(1)
    })

    it('test 5: includes needs-info tickets in needsYou count', async () => {
      const tickets = [
        issue(1, { labels: [{ name: 'ready-for-human' }] }),
        issue(2, { labels: [{ name: 'needs-info' }] })
      ]
      const o = await svc(tickets, []).overview()
      expect(o['G-Eskayo/marvin'].needsYou).toBe(2)
    })
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

  describe('needsYou() regression guards for projectId', () => {
    const pr = (n, body, over = {}) => ({ number: n, title: `PR ${n}`, url: `p${n}`, state: 'OPEN', isDraft: false, body, files: [], ...over })
    const svc = (issues, prs) => make({ getBoardData: async () => ({ issues, prs }) })

    it('test 6: needsYou() includes projectId from rankNeedsYou output', async () => {
      const tickets = [
        issue(1, { labels: [{ name: 'ready-for-human' }] }),
        issue(2, { labels: [{ name: 'needs-info' }] })
      ]
      const rows = await svc(tickets, []).needsYou()
      expect(rows.every((r) => r.projectId !== undefined && typeof r.projectId === 'string')).toBe(true)
    })

    it('test 7: needsYou() uses project: label when present', async () => {
      const tickets = [
        issue(1, { labels: [{ name: 'ready-for-human' }, { name: 'project:custom' }] })
      ]
      const rows = await svc(tickets, []).needsYou()
      expect(rows[0].projectId).toBe('custom')
    })

    it('test 8: needsYou() derives projectId from repo when no project: label', async () => {
      const marvinTickets = [
        issue(1, { labels: [{ name: 'ready-for-human' }] })
      ]
      const s = createRelationsService({
        getRepos: () => ['G-Eskayo/marvin'],
        getBoardData: async () => ({ issues: marvinTickets, prs: [] }),
        getDocs: async () => [],
        getProjects: () => [{ id: 'marvin', repo: 'G-Eskayo/marvin' }]
      })
      const rows = await s.needsYou()
      expect(rows[0].projectId).toBe('marvin')
    })

    it('test 9: overview() counts needsYou correctly per repo regardless of projectId', async () => {
      const tickets = [
        issue(1, { labels: [{ name: 'ready-for-human' }] }),
        issue(2, { labels: [{ name: 'ready-for-human' }, { name: 'project:other' }] }),
        issue(3, { labels: [{ name: 'needs-info' }] })
      ]
      const o = await svc(tickets, []).overview()
      expect(o['G-Eskayo/marvin'].needsYou).toBe(3)
    })
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
