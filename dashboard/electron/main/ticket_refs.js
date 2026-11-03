// How an open PR names its ticket (marvin#1004, docs/agents/issue-tracker.md "A PR names its ticket"):
//   "Closes #N" (also Fixes/Resolves and GitHub's other closing words): the PR finishes the ticket, and GitHub
//   closes it on merge;
//   "Part of #N": the PR is a step (a mock-up, a stacked slice, a plan, docs) and the ticket stays open.
// Either form takes `owner/repo#N` or an issue URL for a ticket in another repo. Either way the ticket is in review.
// A bare mention ("see #N", "for #N") links nothing. lib/pr_ticket_check.py (bin/gh's gate) is the same rule in
// Python; both run dashboard/test/fixtures/pr_ticket_refs_cases.json so they can't drift.

export const stripCode = (text) =>
  String(text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/~~~[\s\S]*?~~~/g, ' ')
    .replace(/`[^`\n]*`/g, ' ')

const REF = String.raw`(?:https?://github\.com/[\w.-]+/[\w.-]+/issues/\d+|(?:[\w.-]+/[\w.-]+)?#\d+)(?![\w-])`
const CLOSES = new RegExp(String.raw`\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+(${REF})`, 'gi')
const PART_OF = new RegExp(String.raw`\bpart of:?\s+(${REF}(?:\s*(?:,|&|\band\b)\s*${REF})*)`, 'gi')
const ONE_REF = new RegExp(REF, 'g')

function parseRef(text, prRepo) {
  const url = text.match(/github\.com\/([\w.-]+\/[\w.-]+)\/issues\/(\d+)/)
  if (url) return { repo: url[1], number: Number(url[2]) }
  const [repo, n] = text.split('#')
  return { repo: repo || prRepo, number: Number(n) }
}

// [{ repo, number, relation: 'closes' | 'part-of' }] in the order written; a ticket named both ways is 'closes'.
export function prTicketRefs(body, prRepo) {
  const text = stripCode(body)
  const found = new Map()
  const put = (ref, relation) => {
    const key = `${String(ref.repo).toLowerCase()}#${ref.number}`
    const had = found.get(key)
    if (!had) found.set(key, { ...ref, relation })
    else if (relation === 'closes') had.relation = 'closes'
  }
  const hits = []
  for (const m of text.matchAll(CLOSES)) hits.push({ at: m.index, refs: [m[1]], relation: 'closes' })
  for (const m of text.matchAll(PART_OF)) hits.push({ at: m.index, refs: m[1].match(ONE_REF), relation: 'part-of' })
  hits.sort((a, b) => a.at - b.at)
  for (const h of hits) for (const r of h.refs) put(parseRef(r, prRepo), h.relation)
  return [...found.values()]
}

// The relation ('closes' / 'part-of') by which this PR names ticket repo#number, else null. A PR with no `repo` is
// taken to be in `defaultRepo` (a board's own PR list carries no repo field).
export function ticketLinked(pr, repo, number, defaultRepo = repo) {
  const want = String(repo).toLowerCase()
  const hit = prTicketRefs(pr.body, pr.repo || defaultRepo).find((r) => r.number === Number(number) && String(r.repo).toLowerCase() === want)
  return hit ? hit.relation : null
}
