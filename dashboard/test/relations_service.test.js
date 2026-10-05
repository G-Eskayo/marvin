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
