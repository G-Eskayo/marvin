import { buildRelationIndex } from './relations.js'
import { buildBoard } from './board.js'

// Feeds relations.js real data (every board's tickets and PRs, every project's docs) and keeps the
// result for a minute; invalidated by the same triggers that refresh the boards and docs.
export function createRelationsService({ getRepos, getBoardData, getDocs, getProjects, getStages = () => ({}), getLive = () => new Set(), recheck = () => {}, ttlMs = 60_000, now = Date.now }) {
  let built = null // { at, index, columns }

  async function build() {
    const tickets = []
    const prs = []
    const columns = new Map()
    const cards = new Map()
    await Promise.all(
      getRepos().map(async (repo) => {
        try {
          const data = await getBoardData(repo)
          for (const i of data.issues) tickets.push({ ...i, repo })
          for (const p of data.prs) prs.push({ ...p, repo })
          // The same inputs the board view uses (pipeline stages, live dispatch), so a ticket is in the
          // same column here as on screen -- the whole point of the parity check.
          const board = buildBoard({ repo, issues: data.issues, prs: data.prs, eventsByNumber: getStages(repo) || {}, liveNumbers: getLive(repo) })
          for (const c of board.columns) {
            for (const card of [...c.cards, ...(c.archive || [])]) {
              columns.set(`${repo}#${card.number}`, c.id)
              cards.set(`${repo}#${card.number}`, { repo, number: card.number, title: card.title, column: c.id, reason: card.reason, owner: card.owner, prs: card.prs })
            }
          }
        } catch {
          // one project's outage must not hide every other project's relations
        }
      })
    )
    const docs = await getDocs().catch(() => [])
    return { at: now(), index: buildRelationIndex({ tickets, prs, docs, projects: getProjects() }), columns, cards, prs }
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
    // One-to-one between MR Review and the boards: every open PR paired with its ticket and that ticket's column,
    // and every ticket filed under "In review" checked against an open PR.
    parity: async () => {
      const compute = (b) => {
      const rows = b.prs.map((p) => {
        const t = b.index.forPr(p.repo, p.number).tickets.find((x) => x.relation === 'closes')
        const card = t && b.cards.get(`${t.repo}#${t.number}`)
        let status = 'no-ticket'
        if (card) status = card.column === 'review' ? 'ok' : card.column === 'blocked' && /sent back/i.test(card.reason) ? 'sent-back' : 'elsewhere'
        return {
          repo: p.repo, number: p.number, title: p.title, url: p.url, key: `${p.repo}#${p.number}`, status,
          ticket: card ? { repo: card.repo, number: card.number, title: card.title, column: card.column, reason: card.reason } : null
        }
      })
      const withPr = new Set(rows.filter((r) => r.ticket).map((r) => `${r.ticket.repo}#${r.ticket.number}`))
      const reviewWithoutPr = [...b.cards.values()].filter((c) => c.column === 'review' && !withPr.has(`${c.repo}#${c.number}`))
      const problems = [
        ...rows.filter((r) => r.status === 'no-ticket').map((r) => `PR #${r.number} (${r.repo.split('/')[1]}) closes no ticket, so no board has a card for it`),
        ...rows.filter((r) => r.status === 'elsewhere').map((r) => `PR #${r.number} is open but its ticket #${r.ticket.number} is filed under ${r.ticket.column}`),
        ...reviewWithoutPr.map((c) => `Ticket #${c.number} (${c.repo.split('/')[1]}) is filed under In review but has no open PR`)
      ]
      return { prs: rows, reviewWithoutPr, problems, ok: problems.length === 0 }
      }
      // Two data sources with different freshness (the local stage log is instant, GitHub's PR list is cached) can
      // briefly disagree. Never alarm on one snapshot: look again with fresh data and report only what persists.
      const first = compute(await ready())
      if (first.ok) return first
      recheck()
      built = null
      return compute(await ready())
    },
    // What is waiting on you, per project, from the same data the boards show.
    overview: async () => {
      const b = await ready()
      const out = {}
      for (const c of b.cards.values()) {
        const o = (out[c.repo] ||= { review: 0, needsYou: 0, blocked: 0 })
        if (c.column === 'review') o.review += 1
        if (c.column === 'ready' && c.owner === 'human') o.needsYou += 1
        if (c.column === 'blocked') o.blocked += 1
      }
      return out
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
