// Relationships between tickets, PRs and docs, derived from the text itself (never maintained by
// hand): a ticket that says "ADR 0033" is related to that ADR, a doc that says "#117" is related to
// that ticket, a PR is related to the docs it changes. Edit a doc or a ticket and the relations
// change with it. CONTEXT.md "Cross-links by project".

// ── extraction ──────────────────────────────────────────────────────────────

const stripCode = (text) =>
  String(text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/~~~[\s\S]*?~~~/g, ' ')
    .replace(/`[^`\n]*`/g, ' ')

export function extractRefs(text) {
  const clean = stripCode(text)
  const tickets = []
  // Qualified (owner/repo#n) first, then blank them out so the bare-#n pass doesn't see them again.
  const unqualified = clean.replace(/\b([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d{1,6})(?![\w-])/g, (_m, repo, n) => {
    tickets.push({ repo, number: Number(n) })
    return ' '
  })
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

function blockedByNumbers(body) {
  const text = stripCode(body)
  const out = new Set()
  for (const m of text.matchAll(/\bBlocked by\s+(?:[\w.-]+\/[\w.-]+)?#(\d+)/gi)) out.add(Number(m[1]))
  const sec = text.match(/##\s*Blocked by\s*\n([\s\S]*?)(?=\n##\s|$)/i)
  if (sec) for (const m of sec[1].matchAll(/#(\d+)/g)) out.add(Number(m[1]))
  return out
}

function closesNumbers(body) {
  const out = new Set()
  for (const m of stripCode(body).matchAll(/\b(?:Closes|Fixes|Resolves)\s+(?:([\w.-]+\/[\w.-]+))?#(\d+)/gi)) out.add(`${m[1] || ''}#${m[2]}`)
  return out
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
    const blocked = blockedByNumbers(t.body)
    for (const n of blocked) add(me, T(tk(t.repo, n)), 'blocked-by')
    for (const r of refs.tickets) if (!(r.repo === null || r.repo === t.repo) || !blocked.has(r.number)) add(me, T(tk(r.repo || t.repo, r.number)), 'mentions')
    if (project) for (const d of docsMentioned(refs, project)) add(me, D(dk(d.project, d.path)), 'mentions')
  }

  for (const p of prs) {
    const me = P(tk(p.repo, p.number))
    const project = projectByRepo[p.repo]
    for (const c of closesNumbers(p.body)) {
      const [repo, n] = c.split('#')
      add(me, T(tk(repo || p.repo, n)), 'closes')
    }
    const refs = extractRefs(`${p.title}\n${p.body}`)
    for (const r of refs.tickets) add(me, T(tk(r.repo || p.repo, r.number)), 'mentions')
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
  const OUT_WORD = { 'blocked-by': 'blocked by', mentions: 'mentions', closes: 'closes', changes: 'changes' }
  const IN_WORD = { 'blocked-by': 'blocks', mentions: 'mentioned in', closes: 'closed by', changes: 'changed by' }

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
