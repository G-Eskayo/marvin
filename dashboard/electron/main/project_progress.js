import { isActive } from '../../src/lib/project_goals.js'

// Activity's projects list (marvin#625's progress strip, without its timeline): one row per active project with its
// goal, signals and whether it is moving or stuck. Built only from what the dashboard already holds: the profiles'
// goals, the board registry, the cached board data (github_state 'board'), the boards' overview, the local stage
// logs and the saved merge record. No GitHub call of its own. O(projects + cached tickets + merges).

const WEEK_MS = 7 * 24 * 3600_000
const DAY_MS = 24 * 3600_000
const PR_URL = /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/pull\/\d+$/

// Tickets planned 3 or more times in the last 24 hours (the loop alarm's rule, marvin#625).
export function loopingTickets(stagesByNumber, now = Date.now()) {
  const out = []
  for (const [n, events] of Object.entries(stagesByNumber || {})) {
    if (!Array.isArray(events)) continue
    const plans = events.filter((e) => e && e.stage === 'planning' && e.status === 'started' && now - Date.parse(e.timestamp) <= DAY_MS && Date.parse(e.timestamp) <= now)
    if (plans.length >= 3) out.push(Number(n))
  }
  return out
}

export function buildProgressRows({ goals, boards, overview, merged, issuesByRepo, stagesByRepo, now = Date.now() } = {}) {
  const list = Array.isArray(goals) ? goals : []
  const boardList = Array.isArray(boards) ? boards : []
  const order = new Map(boardList.map((b, i) => [b.repo, i]))
  const names = new Map(boardList.map((b) => [b.repo, b.name]))

  const weekByRepo = new Map()
  const seen = new Set()
  for (const m of Array.isArray(merged) ? merged : []) {
    const hit = m && PR_URL.exec(m.url || '')
    const at = hit ? Date.parse(m.at) : NaN
    if (!hit || Number.isNaN(at) || at > now || now - at > WEEK_MS || seen.has(m.url)) continue
    seen.add(m.url)
    weekByRepo.set(hit[1], (weekByRepo.get(hit[1]) || 0) + 1)
  }

  const rows = list
    .filter((g) => g && g.repo)
    .map((g, i) => {
      const issues = (issuesByRepo || {})[g.repo] || []
      const closed = new Set(issues.filter((x) => x.state === 'CLOSED').map((x) => x.number))
      const held = issues.filter((x) => x.state === 'OPEN' && (x.labels || []).some((l) => l.name === 'hold')).length
      const looping = loopingTickets((stagesByRepo || {})[g.repo], now).filter((n) => !closed.has(n)).length
      const needsYou = Number((overview || {})[g.repo]?.needsYou) || 0
      return {
        repo: g.repo,
        name: names.get(g.repo) || g.repo.split('/').pop(),
        hasBoard: names.has(g.repo),
        goal: g.goal,
        signals: g.signals || [],
        status: g.status,
        mergedWeek: weekByRepo.get(g.repo) || 0,
        stuck: { held, needsYou, looping, total: held + needsYou + looping },
        sort: order.has(g.repo) ? order.get(g.repo) : boardList.length + i
      }
    })
    .sort((a, b) => a.sort - b.sort)
    .map(({ sort, ...r }) => r)
  return { active: rows.filter(isActive), rest: rows.filter((r) => !isActive(r)) }
}
