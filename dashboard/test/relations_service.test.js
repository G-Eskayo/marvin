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
