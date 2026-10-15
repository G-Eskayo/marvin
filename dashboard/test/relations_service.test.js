import { describe, it, expect, vi } from 'vitest'
import { createRelationsService, resolveProjectRepo } from '../electron/main/relations_service.js'

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

  it('resolves project:<id> labels in needsYou rows', async () => {
    const otherProject = { id: 'other', repo: 'G-Eskayo/other' }
    const s = make({ getProjects: () => [...projects, otherProject] })
    const rows = await s.needsYou()
    expect(rows).toEqual([])

    const s2 = make({
      getProjects: () => [...projects, otherProject],
      getBoardData: async () => ({
        issues: [issue(1, { labels: [{ name: 'ready-for-human' }, { name: 'project:other' }] })],
        prs: []
      })
    })
    const rows2 = await s2.needsYou()
    expect(rows2).toHaveLength(1)
    expect(rows2[0]).toMatchObject({ projectRepo: 'G-Eskayo/other', repo: 'G-Eskayo/marvin', number: 1 })
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

  it('counts needs-info tickets in needsYou (filed under backlog)', async () => {
    const o = await svc(
      [issue(2), issue(3, { labels: [{ name: 'needs-info' }] })],
      []
    ).overview()
    expect(o['G-Eskayo/marvin']).toMatchObject({ needsYou: 1 })
  })

  it('counts a project:<id> ticket under its resolved project, not its repo', async () => {
    const otherProject = { id: 'other', repo: 'G-Eskayo/other' }
    const s = make({
      getProjects: () => [...projects, otherProject],
      getBoardData: async () => ({
        issues: [issue(2, { labels: [{ name: 'ready-for-human' }, { name: 'project:other' }] })],
        prs: []
      })
    })
    const o = await s.overview()
    // The ticket is filed in G-Eskayo/marvin but labels it to G-Eskayo/other
    expect(o['G-Eskayo/marvin']?.needsYou || 0).toBe(0) // not counted under original repo
    expect(o['G-Eskayo/other']).toMatchObject({ needsYou: 1 }) // counted under resolved repo
  })

  it('overview count matches needsYou list length', async () => {
    const otherProject = { id: 'other', repo: 'G-Eskayo/other' }
    const s = make({
      getProjects: () => [...projects, otherProject],
      getBoardData: async () => ({
        issues: [
          issue(1, { labels: [{ name: 'ready-for-human' }] }),
          issue(2, { labels: [{ name: 'ready-for-human' }, { name: 'project:other' }] }),
          issue(3, { labels: [{ name: 'needs-info' }] })
        ],
        prs: []
      })
    })
    const overview = await s.overview()
    const rows = await s.needsYou()
    expect(rows).toHaveLength(3)
    const totalCount = Object.values(overview).reduce((sum, o) => sum + o.needsYou, 0)
    expect(totalCount).toBe(3)
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

describe('resolveProjectRepo helper', () => {
  it('returns fallbackRepo when ticket is undefined', () => {
    const fallback = 'G-Eskayo/marvin'
    expect(resolveProjectRepo(undefined, {}, fallback)).toBe(fallback)
  })

  it('returns fallbackRepo when ticket is null', () => {
    const fallback = 'G-Eskayo/marvin'
    expect(resolveProjectRepo(null, {}, fallback)).toBe(fallback)
  })

  it('returns fallbackRepo when ticket has no labels', () => {
    const fallback = 'G-Eskayo/marvin'
    const ticket = { repo: 'G-Eskayo/other', number: 1 }
    expect(resolveProjectRepo(ticket, {}, fallback)).toBe(fallback)
  })

  it('returns ticket.repo when no project:<id> label found', () => {
    const ticket = { repo: 'G-Eskayo/marvin', labels: [{ name: 'ready-for-human' }] }
    expect(resolveProjectRepo(ticket, {}, 'G-Eskayo/fallback')).toBe('G-Eskayo/marvin')
  })

  it('returns resolved project repo when project:<id> label exists', () => {
    const ticket = { repo: 'G-Eskayo/marvin', labels: [{ name: 'project:other' }] }
    const projectById = { other: { id: 'other', repo: 'G-Eskayo/other' } }
    expect(resolveProjectRepo(ticket, projectById, 'G-Eskayo/fallback')).toBe('G-Eskayo/other')
  })

  it('ignores unknown project:<id> labels and falls back to ticket.repo', () => {
    const ticket = { repo: 'G-Eskayo/marvin', labels: [{ name: 'project:unknown' }] }
    expect(resolveProjectRepo(ticket, {}, 'G-Eskayo/fallback')).toBe('G-Eskayo/marvin')
  })
})

describe('needsYou excludes hold/pinned tickets', () => {
  const issue = (n, over = {}) => ({ number: n, title: `T${n}`, state: 'OPEN', labels: [], body: '', url: `u${n}`, createdAt: '2026-10-01T00:00:00Z', ...over })

  it('filters out hold-labeled tickets from needsYou list', async () => {
    const s = createRelationsService({
      getRepos: () => ['G-Eskayo/marvin'],
      getBoardData: async () => ({
        issues: [
          issue(1, { labels: [{ name: 'ready-for-human' }] }),
          issue(2, { labels: [{ name: 'ready-for-human' }, { name: 'hold' }] })
        ],
        prs: []
      }),
      getDocs: async () => [],
      getProjects: () => [{ id: 'marvin', repo: 'G-Eskayo/marvin' }]
    })
    const rows = await s.needsYou()
    expect(rows.map((r) => r.number)).toEqual([1])
  })

  it('filters out pinned-labeled tickets from needsYou list', async () => {
    const s = createRelationsService({
      getRepos: () => ['G-Eskayo/marvin'],
      getBoardData: async () => ({
        issues: [
          issue(1, { labels: [{ name: 'ready-for-human' }] }),
          issue(2, { labels: [{ name: 'ready-for-human' }, { name: 'pinned' }] })
        ],
        prs: []
      }),
      getDocs: async () => [],
      getProjects: () => [{ id: 'marvin', repo: 'G-Eskayo/marvin' }]
    })
    const rows = await s.needsYou()
    expect(rows.map((r) => r.number)).toEqual([1])
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
