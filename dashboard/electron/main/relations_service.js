import { buildRelationIndex } from './relations.js'
import { buildBoard } from './board.js'

// Feeds relations.js real data (every board's tickets and PRs, every project's docs) and keeps the
// result for a minute; invalidated by the same triggers that refresh the boards and docs.
export function createRelationsService({ getRepos, getBoardData, getDocs, getProjects, ttlMs = 60_000, now = Date.now }) {
  let built = null // { at, index, columns }

  async function build() {
    const tickets = []
    const prs = []
    const columns = new Map()
    await Promise.all(
      getRepos().map(async (repo) => {
        try {
          const data = await getBoardData(repo)
          for (const i of data.issues) tickets.push({ ...i, repo })
          for (const p of data.prs) prs.push({ ...p, repo })
          for (const c of buildBoard({ repo, issues: data.issues, prs: data.prs }).columns) {
            for (const card of [...c.cards, ...(c.archive || [])]) columns.set(`${repo}#${card.number}`, c.id)
          }
        } catch {
          // one project's outage must not hide every other project's relations
        }
      })
    )
    const docs = await getDocs().catch(() => [])
    return { at: now(), index: buildRelationIndex({ tickets, prs, docs, projects: getProjects() }), columns }
  }

  async function ready() {
    if (!built || now() - built.at > ttlMs) built = await build()
    return built
  }

  const withColumns = (r, columns) => ({ ...r, tickets: r.tickets.map((t) => ({ ...t, column: columns.get(`${t.repo}#${t.number}`) || null })) })

  return {
    invalidate: () => {
      built = null
    },
    forTicket: async (repo, number) => {
      const b = await ready()
      return withColumns(b.index.forTicket(repo, number), b.columns)
    },
    forDoc: async (project, path) => {
      const b = await ready()
      return withColumns(b.index.forDoc(project, path), b.columns)
    },
    forPr: async (repo, number) => {
      const b = await ready()
      return withColumns(b.index.forPr(repo, number), b.columns)
    },
    // What linkify needs to turn "#12" and "ADR 0033" in this project's text into links.
    context: async (project) => {
      const p = getProjects().find((x) => x.id === project)
      const adrs = {}
      for (const d of await getDocs().catch(() => [])) {
        const m = d.project === project && d.path.match(/^docs\/adr\/0*(\d+)-/)
        if (m) adrs[Number(m[1])] = d.path
      }
      return { project, repo: p?.repo || null, adrs }
    }
  }
}
