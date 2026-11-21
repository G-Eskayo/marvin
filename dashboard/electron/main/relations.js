// Relationships between tickets, PRs and docs, derived from the text itself (never maintained by
// hand): a ticket that says "ADR 0033" is related to that ADR, a doc that says "#117" is related to
// that ticket, a PR is related to the docs it changes. Edit a doc or a ticket and the relations
// change with it. CONTEXT.md "Cross-links by project".

// ── extraction ──────────────────────────────────────────────────────────────

import { stripCode, prTicketRefs, relationRefs } from './ticket_refs.js'

// Scan for section-bullet format "## Blocked by\n- #n" that regex patterns in relationRefs don't match
function sectionBlockedBy(body, repo) {
  const found = []
  const sec = (body || '').match(/##\s*Blocked by\s*\n([\s\S]*?)(?=\n##\s|$)/i)
  if (!sec) return found
  // Match refs in section bullets: "- #n", "- owner/repo#n", or GitHub URLs
  // The \b and (?![\w-]) guards prevent matching partial words like "#5abc"
  for (const m of sec[1].matchAll(/(?:https?:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/issues\/(\d+)|(?<!\/)(?:[\w.-]+\/[\w.-]+)?#(\d+))(?![\w-])/g)) {
    if (m[1]) {
      // GitHub URL form
      found.push({ repo: m[1], number: Number(m[2]), relation: 'blocked-by' })
    } else {
      // #n or owner/repo#n form
      const ref = m[0]
      const urlMatch = ref.match(/^([\w.-]+\/[\w.-]+)#/)
      const refRepo = urlMatch ? urlMatch[1] : repo
      const num = Number(ref.match(/\d+$/)[0])
      found.push({ repo: refRepo, number: num, relation: 'blocked-by' })
    }
  }
  return found
}

// Opt-in readings for prose that names work the way people write it (the handoff resume check, marvin#1221):
//   repos  {shortName: 'owner/repo'}: "portfolio-website-updater #17" (or "marvin#5") is that repo's (an unknown name stays bare)
//   words  "ticket 1185", "PR 20", "PRs 20, 21 and 22", "issue #9" are bare refs
// Without them the dashboard's relations read exactly as before.
export function extractRefs(text, { repos = null, words = false } = {}) {
  const clean = stripCode(text)
  const tickets = []
  // Qualified (owner/repo#n) first, then blank them out so the bare-#n pass doesn't see them again.
  let unqualified = clean.replace(/\b([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d{1,6})(?![\w-])/g, (_m, repo, n) => {
    tickets.push({ repo, number: Number(n) })
    return ' '
  })
  if (repos) {
    unqualified = unqualified.replace(/(?<![\w/.-])([A-Za-z0-9_.-]+)\s*#(\d{1,6})(?![\w-])/g, (m, name, n) => {
      const repo = repos[name] || repos[name.toLowerCase()]
      if (!repo) return m
      tickets.push({ repo, number: Number(n) })
      return ' '
    })
  }
  if (words) {
    const LIST = /\b(?:tickets?|issues?|PRs?|pull requests?)\s+#?(\d{1,6})((?:\s*(?:,|&|\band\b)\s*#?\d{1,6}(?![\w-]))*)(?![\w-])/gi
    unqualified = unqualified.replace(LIST, (_m, first, rest) => {
      tickets.push({ repo: null, number: Number(first) })
      for (const x of rest.matchAll(/\d{1,6}/g)) tickets.push({ repo: null, number: Number(x[0]) })
      return ' '
    })
  }
  for (const m of unqualified.matchAll(/(?<![\w/&#])#(\d{1,6})(?![\w-])/g)) tickets.push({ repo: null, number: Number(m[1]) })

  const adrs = new Set()
  for (const m of clean.matchAll(/\bADR[ -]?0*(\d{1,4})\b/gi)) adrs.add(Number(m[1]))
  const paths = [...new Set(clean.match(/docs\/adr\/[\w.-]+\.md/g) || [])]
  for (const p of paths) {
    const n = p.match(/docs\/adr\/0*(\d+)-/)
    if (n) adrs.add(Number(n[1]))
  }
  return { tickets, adrs: [...adrs], paths, context: /\bCONTEXT\.md\b/.test(clean), readme: /\bREADME\.md\b/.test(clean) }
}


// ── index ───────────────────────────────────────────────────────────────────

export function buildRelationIndex({ tickets = [], prs = [], docs = [], projects = [] }) {
  const projectByRepo = Object.fromEntries(projects.filter((p) => p.repo).map((p) => [p.repo, p.id]))
  const repoByProject = Object.fromEntries(projects.filter((p) => p.repo).map((p) => [p.id, p.repo]))
  const tk = (repo, n) => `${repo}#${n}`
  const dk = (project, path) => `${project}/${path}`

  const ticketNodes = new Map(tickets.map((t) => [tk(t.repo, t.number), t]))
  const prNodes = new Map(prs.map((p) => [tk(p.repo, p.number), p]))
  const docNodes = new Map(docs.map((d) => [dk(d.project, d.path), d]))
  const docsOfProject = new Map()
  for (const d of docs) docsOfProject.set(d.project, [...(docsOfProject.get(d.project) || []), d])
  const adrDoc = (project, n) => (docsOfProject.get(project) || []).find((d) => new RegExp(`^docs/adr/0*${n}-`).test(d.path))

  const edges = new Map() // "type:key>type:key|kind" -> edge (one per pair and kind)
  const add = (from, to, kind) => {
    if (from.type === to.type && from.key === to.key) return
    edges.set(`${from.type}:${from.key}>${to.type}:${to.key}|${kind}`, { from, to, kind })
  }
  const T = (key) => ({ type: 't', key })
  const P = (key) => ({ type: 'p', key })
  const D = (key) => ({ type: 'd', key })

  function docsMentioned(refs, project) {
    const found = []
    for (const n of refs.adrs) {
      const d = adrDoc(project, n)
      if (d) found.push(d)
    }
    for (const path of refs.paths) {
      const d = docNodes.get(dk(project, path))
      if (d) found.push(d)
    }
    if (refs.context && docNodes.has(dk(project, 'CONTEXT.md'))) found.push(docNodes.get(dk(project, 'CONTEXT.md')))
    if (refs.readme && docNodes.has(dk(project, 'README.md'))) found.push(docNodes.get(dk(project, 'README.md')))
    return found
  }

  for (const t of tickets) {
    const me = T(tk(t.repo, t.number))
    const project = projectByRepo[t.repo]
    const refs = extractRefs(`${t.title}\n${t.body}`)
    const rels = relationRefs(t.body, t.repo)
    // Also scan for section-bullet format "## Blocked by\n- #n" that inline regex misses
    // Use stripCode output so refs in code blocks don't trigger
    const secBlockedBy = sectionBlockedBy(stripCode(t.body), t.repo)
    const allRels = [...rels, ...secBlockedBy]
    const relKeys = new Set(allRels.map((r) => tk(r.repo, r.number)))
    for (const r of allRels) add(me, T(tk(r.repo, r.number)), r.relation)
    for (const r of refs.tickets) if (!relKeys.has(tk(r.repo || t.repo, r.number))) add(me, T(tk(r.repo || t.repo, r.number)), 'mentions')
    if (project) for (const d of docsMentioned(refs, project)) add(me, D(dk(d.project, d.path)), 'mentions')
  }

  for (const p of prs) {
    const me = P(tk(p.repo, p.number))
    const project = projectByRepo[p.repo]
    // "Closes #n" finishes the ticket, "Part of #n" is a step towards it (ticket_refs.js, marvin#1004); either
    // may name a ticket in another repo. Also capture other relations (blocked-by, duplicate-of, etc.) from the PR body.
    const rels = relationRefs(p.body, p.repo)
    const relKeys = new Set()
    for (const r of rels) {
      const targetKey = tk(r.repo, r.number)
      relKeys.add(targetKey)
      // Closes and part-of link to tickets; other relations also link to tickets (not PRs).
      add(me, T(targetKey), r.relation)
    }
    const refs = extractRefs(`${p.title}\n${p.body}`)
    for (const r of refs.tickets) if (!relKeys.has(tk(r.repo || p.repo, r.number))) add(me, T(tk(r.repo || p.repo, r.number)), 'mentions')
    if (project) {
      for (const d of docsMentioned(refs, project)) add(me, D(dk(d.project, d.path)), 'mentions')
      for (const f of p.files || []) if (docNodes.has(dk(project, f.path))) add(me, D(dk(project, f.path)), 'changes')
    }
  }

  for (const d of docs) {
    const me = D(dk(d.project, d.path))
    const refs = extractRefs(d.content)
    const repo = repoByProject[d.project]
    for (const r of refs.tickets) {
      const target = r.repo || repo
      if (target) add(me, T(tk(target, r.number)), 'mentions')
    }
    for (const other of docsMentioned(refs, d.project)) add(me, D(dk(other.project, other.path)), 'mentions')
  }

  // ── queries ───────────────────────────────────────────────────────────────
  const infoT = (key) => {
    const n = ticketNodes.get(key)
    const [repo, num] = [key.slice(0, key.lastIndexOf('#')), Number(key.slice(key.lastIndexOf('#') + 1))]
    return { repo, number: num, title: n?.title || '(not loaded)', state: n?.state || 'UNKNOWN', url: n?.url || null }
  }
  const infoP = (key) => {
    const n = prNodes.get(key)
    return { repo: key.slice(0, key.lastIndexOf('#')), number: Number(key.slice(key.lastIndexOf('#') + 1)), title: n?.title || '(not loaded)', state: n?.state || 'UNKNOWN', url: n?.url || null }
  }
  const infoD = (key) => {
    const n = docNodes.get(key)
    return { project: n?.project || key.split('/')[0], path: n?.path || key.slice(key.indexOf('/') + 1), label: n?.label || key }
  }
  const INFO = { t: infoT, p: infoP, d: infoD }
  const OUT_WORD = {
    'blocked-by': 'blocked by',
    'duplicate-of': 'duplicate of',
    'covered-by': 'covered by',
    supersedes: 'supersedes',
    'related-to': 'related to',
    mentions: 'mentions',
    closes: 'closes',
    'part-of': 'part of',
    changes: 'changes'
  }
  const IN_WORD = {
    'blocked-by': 'blocks',
    'duplicate-of': 'duplicated by',
    'covered-by': 'covers',
    supersedes: 'superseded by',
    'related-to': 'related to',
    mentions: 'mentioned in',
    closes: 'closed by',
    'part-of': 'worked on in',
    changes: 'changed by'
  }

  function around(type, key) {
    const out = { docs: [], tickets: [], prs: [] }
    const bucket = { t: out.tickets, p: out.prs, d: out.docs }
    const seen = new Set()
    const take = (otherType, otherKey, relation) => {
      const id = `${otherType}:${otherKey}`
      if (seen.has(id)) return // strongest relation first (edges are visited blocked-by/closes before mentions below)
      seen.add(id)
      bucket[otherType].push({ ...INFO[otherType](otherKey), relation })
    }
    const all = [...edges.values()]
    const rank = (e) => (e.kind === 'mentions' ? 1 : 0)
    for (const e of all.filter((x) => x.from.type === type && x.from.key === key).sort((a, b) => rank(a) - rank(b))) take(e.to.type, e.to.key, OUT_WORD[e.kind])
    for (const e of all.filter((x) => x.to.type === type && x.to.key === key).sort((a, b) => rank(a) - rank(b))) take(e.from.type, e.from.key, IN_WORD[e.kind])
    return out
  }

  return {
    forTicket: (repo, number) => around('t', tk(repo, number)),
    forDoc: (project, path) => around('d', dk(project, path)),
    forPr: (repo, number) => around('p', tk(repo, number)),
    edgeCount: edges.size
  }
}

export { linkify } from '../../src/lib/linkify.js'
