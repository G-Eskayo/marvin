// How an open PR names its ticket (marvin#1004, docs/agents/issue-tracker.md "A PR names its ticket"):
//   "Closes #N" (also Fixes/Resolves and GitHub's other closing words): the PR finishes the ticket, and GitHub
//   closes it on merge;
//   "Part of #N": the PR is a step (a mock-up, a stacked slice, a plan, docs) and the ticket stays open.
// Either form takes `owner/repo#N` or an issue URL for a ticket in another repo. Either way the ticket is in review.
// A bare mention ("see #N", "for #N") links nothing. lib/pr_ticket_check.py (bin/gh's gate) is the same rule in
// Python; both run dashboard/test/fixtures/pr_ticket_refs_cases.json so they can't drift.
//
// Tickets can also link to other tickets with 5 more relations (dashboard/electron/main/relations.js):
// "Blocked by #N", "Duplicate of #N", "Covered by #N", "Supersedes #N", "Related to #N".

export const stripCode = (text) =>
  String(text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/~~~[\s\S]*?~~~/g, ' ')
    .replace(/`[^`\n]*`/g, ' ')

const REF = String.raw`(?:https?://github\.com/[\w.-]+/[\w.-]+/issues/\d+|(?:[\w.-]+/[\w.-]+)?#\d+)(?![\w-])`
const CLOSES = new RegExp(String.raw`\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+(${REF})`, 'gi')
const PART_OF = new RegExp(String.raw`\bpart of:?\s+(${REF}(?:\s*(?:,|&|\band\b)\s*${REF})*)`, 'gi')
const BLOCKED_BY = new RegExp(String.raw`\bblocked by:?\s+(${REF}(?:\s*(?:,|&|\band\b)\s*${REF})*)`, 'gi')
const DUPLICATE_OF = new RegExp(String.raw`\bduplicate of:?\s+(${REF}(?:\s*(?:,|&|\band\b)\s*${REF})*)`, 'gi')
const COVERED_BY = new RegExp(String.raw`\bcovered by:?\s+(${REF}(?:\s*(?:,|&|\band\b)\s*${REF})*)`, 'gi')
const SUPERSEDES = new RegExp(String.raw`\bsupersedes:?\s+(${REF}(?:\s*(?:,|&|\band\b)\s*${REF})*)`, 'gi')
const RELATED_TO = new RegExp(String.raw`\brelated to:?\s+(${REF}(?:\s*(?:,|&|\band\b)\s*${REF})*)`, 'gi')
const ONE_REF = new RegExp(REF, 'g')

function parseRef(text, prRepo) {
  const url = text.match(/github\.com\/([\w.-]+\/[\w.-]+)\/issues\/(\d+)/)
  if (url) return { repo: url[1], number: Number(url[2]) }
  const [repo, n] = text.split('#')
  return { repo: repo || prRepo, number: Number(n) }
}

// [{ repo, number, relation: 'closes' | 'part-of' | 'blocked-by' | ... }] in the order written.
// For PR-specific relations (closes/part-of), 'closes' takes precedence when the same ticket is named both ways.
// PR-specific relations always win over other relation types.
export function allTicketRefs(body, prRepo) {
  const text = stripCode(body)
  const found = new Map()
  const put = (ref, relation) => {
    const key = `${String(ref.repo).toLowerCase()}#${ref.number}`
    const had = found.get(key)
    if (!had) found.set(key, { ...ref, relation })
    else {
      // PR-specific relations (closes/part-of) always win over other relation types
      const isPrRelation = (rel) => rel === 'closes' || rel === 'part-of'
      if (isPrRelation(relation) && !isPrRelation(had.relation)) {
        had.relation = relation
      } else if (isPrRelation(relation) && isPrRelation(had.relation) && relation === 'closes') {
        // Among PR-specific relations, closes wins over part-of
        had.relation = 'closes'
      }
    }
  }
  const hits = []
  for (const m of text.matchAll(CLOSES)) hits.push({ at: m.index, refs: [m[1]], relation: 'closes' })
  for (const m of text.matchAll(PART_OF)) hits.push({ at: m.index, refs: m[1].match(ONE_REF), relation: 'part-of' })
  for (const m of text.matchAll(BLOCKED_BY)) hits.push({ at: m.index, refs: m[1].match(ONE_REF), relation: 'blocked-by' })
  for (const m of text.matchAll(DUPLICATE_OF)) hits.push({ at: m.index, refs: m[1].match(ONE_REF), relation: 'duplicate-of' })
  for (const m of text.matchAll(COVERED_BY)) hits.push({ at: m.index, refs: m[1].match(ONE_REF), relation: 'covered-by' })
  for (const m of text.matchAll(SUPERSEDES)) hits.push({ at: m.index, refs: m[1].match(ONE_REF), relation: 'supersedes' })
  for (const m of text.matchAll(RELATED_TO)) hits.push({ at: m.index, refs: m[1].match(ONE_REF), relation: 'related-to' })
  hits.sort((a, b) => a.at - b.at)
  for (const h of hits) for (const r of h.refs) put(parseRef(r, prRepo), h.relation)
  return [...found.values()]
}

// [{ repo, number, relation: 'closes' | 'part-of' }] in the order written; a ticket named both ways is 'closes'.
// For backward compatibility, this returns only PR-specific relations.
export function prTicketRefs(body, prRepo) {
  return allTicketRefs(body, prRepo).filter((r) => r.relation === 'closes' || r.relation === 'part-of')
}

// The relation ('closes' / 'part-of') by which this PR names ticket repo#number, else null. A PR with no `repo` is
// taken to be in `defaultRepo` (a board's own PR list carries no repo field).
export function ticketLinked(pr, repo, number, defaultRepo = repo) {
  const want = String(repo).toLowerCase()
  const hit = prTicketRefs(pr.body, pr.repo || defaultRepo).find((r) => r.number === Number(number) && String(r.repo).toLowerCase() === want)
  return hit ? hit.relation : null
}
