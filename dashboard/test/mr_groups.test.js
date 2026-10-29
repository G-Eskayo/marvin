import { describe, it, expect } from 'vitest'
import {
  projectOfPr, tierOf, sortPrs, groupPrs, allView, needsYouSummary,
  isCollapsed, toggleCollapsed, placeValue, historyItem, diffGroups, helperFor, OTHER, TIERS
} from '../src/lib/mr_groups.js'

const PROJECTS = [
  { id: 'marvin', name: 'MARVIN', repo: 'G-Eskayo/marvin' },
  { id: 'clarity-captions', name: 'Seal Speak', repo: 'G-Eskayo/clarity-captions' },
  { id: 'portfolio-website-updater', name: 'Portfolio', repo: 'G-Eskayo/portfolio-website-updater' },
  { id: 'marvin-mobile', name: 'MARVIN Mobile', repo: 'G-Eskayo/marvin-mobile' },
  { id: 'nourished', name: 'nourished', repo: 'G-Eskayo/nourished' },
  { id: 'eagle-project', name: 'eagle project', repo: null }
]

// The fields MR Review's cards already carry (mr_review.js listPipelinePrs), plus labels and isDraft, which the list
// would need to ask GitHub for once this is wired.
const pr = (number, extra = {}) => ({
  number, repo: 'G-Eskayo/marvin', key: `${extra.repo || 'G-Eskayo/marvin'}#${number}`, title: `PR ${number}`,
  url: `https://github.com/${extra.repo || 'G-Eskayo/marvin'}/pull/${number}`,
  checks: { state: 'passing', failing: [], pending: [] }, labels: [], isDraft: false, ...extra
})
const label = (name) => ({ name })

describe('projectOfPr: ADR 0060, a PR belongs to its repo project unless labelled project:<id>', () => {
  it('uses the repo project', () => {
    expect(projectOfPr(pr(1, { repo: 'G-Eskayo/clarity-captions' }), PROJECTS)).toEqual({ id: 'clarity-captions', why: 'repo' })
  })
  it('a project: label wins over the repo (the website tools live in MARVIN repo)', () => {
    const p = pr(2, { labels: [label('enhancement'), label('project:portfolio-website-updater')] })
    expect(projectOfPr(p, PROJECTS)).toEqual({ id: 'portfolio-website-updater', why: 'label' })
  })
  it('labels may be plain strings too', () => {
    expect(projectOfPr(pr(3, { labels: ['project:marvin-mobile'] }), PROJECTS).id).toBe('marvin-mobile')
  })
  it('matches the repo case-insensitively', () => {
    expect(projectOfPr(pr(4, { repo: 'g-eskayo/Nourished' }), PROJECTS).id).toBe('nourished')
  })
  it('a repo the catalog has no repo for but whose name slugs to a catalog id still finds it', () => {
    const projects = [...PROJECTS, { id: 'ml-powered-thing', name: 'ML-Powered thing', repo: null }]
    expect(projectOfPr(pr(5, { repo: 'G-Eskayo/ML-Powered_Thing' }), projects).id).toBe('ml-powered-thing')
  })
  it('a repo nobody knows goes to Other, never dropped', () => {
    expect(projectOfPr(pr(6, { repo: 'someone/else' }), PROJECTS)).toEqual({ id: OTHER, why: 'unknown-repo' })
  })
  it('a label naming no catalog project goes to Other (a typo must not invent a group)', () => {
    expect(projectOfPr(pr(7, { labels: ['project:portfolo'] }), PROJECTS)).toEqual({ id: OTHER, why: 'unknown-label' })
  })
  it('two different project labels is ambiguous: Other, so it is seen and fixed', () => {
    const p = pr(8, { labels: ['project:marvin-mobile', 'project:portfolio-website-updater'] })
    expect(projectOfPr(p, PROJECTS)).toEqual({ id: OTHER, why: 'two-labels' })
  })
  it('the same label twice is not ambiguous', () => {
    expect(projectOfPr(pr(9, { labels: ['project:marvin-mobile', label('project:marvin-mobile')] }), PROJECTS).id).toBe('marvin-mobile')
  })
  it('no catalog at all (it failed to load) puts everything in Other rather than hiding it', () => {
    expect(projectOfPr(pr(10), null).id).toBe(OTHER)
    expect(projectOfPr(pr(10), []).id).toBe(OTHER)
  })
  it('a PR with no repo field is MARVIN repo, as mr_review.js treats it', () => {
    const p = pr(11); delete p.repo
    expect(projectOfPr(p, PROJECTS).id).toBe('marvin')
  })
})

describe('tierOf: needs you, then running, then waiting on other PRs, then stuck elsewhere, then drafts', () => {
  it('ready to merge needs you', () => expect(tierOf(pr(1))).toBe('needs-you'))
  it('open decisions need you', () => expect(tierOf(pr(1, { decisions: { pending: ['look'], problems: [] } }))).toBe('needs-you'))
  it('a ticket already closed needs you (close the PR)', () => expect(tierOf(pr(1, { ticketClosed: true, ticketRef: 3 }))).toBe('needs-you'))
  it('a vague ask needs you (send it back for options)', () => expect(tierOf(pr(1, { vague: { reasons: ['A or B?'] } }))).toBe('needs-you'))
  it('running checks are running', () => expect(tierOf(pr(1, { checks: { state: 'pending', failing: [], pending: ['test'] } }))).toBe('running'))
  it('merge order is waiting', () => expect(tierOf(pr(2, { waitingOn: [{ number: 1, shared: ['a'] }] }))).toBe('waiting'))
  it('stacked is waiting', () => expect(tierOf(pr(2, { baseProblem: { base: 'x', expected: 'main', parent: { number: 1 } } }))).toBe('waiting'))
  it('a conflict is stuck', () => expect(tierOf(pr(1, { conflicts: true }))).toBe('stuck'))
  it('failing checks are stuck', () => expect(tierOf(pr(1, { checks: { state: 'failing', failing: ['t'], pending: [] } }))).toBe('stuck'))
  it('sent back is stuck', () => expect(tierOf(pr(1, { sentBack: true }))).toBe('stuck'))
  it('missing images is stuck', () => expect(tierOf(pr(1, { needsImages: { files: ['a.jsx'] } }))).toBe('stuck'))
  it('a draft is a draft whatever else it says, even ready', () => {
    expect(tierOf(pr(1, { isDraft: true }))).toBe('draft')
    expect(tierOf(pr(1, { isDraft: true, decisions: { pending: ['x'], problems: [] } }))).toBe('draft')
  })
  it('a merge in progress on this screen is running', () => expect(tierOf(pr(1), { status: 'approving' })).toBe('running'))
  it('every tier is listed in display order', () => expect(TIERS.map((t) => t.id)).toEqual(['needs-you', 'running', 'waiting', 'stuck', 'draft']))
})

describe('sortPrs: tier, then what kind inside it, then oldest first (the merge order)', () => {
  it('puts the tiers in order', () => {
    const draft = pr(1, { isDraft: true })
    const stuck = pr(2, { conflicts: true })
    const waiting = pr(3, { waitingOn: [{ number: 2, shared: ['a'] }] })
    const running = pr(4, { checks: { state: 'pending', failing: [], pending: ['t'] } })
    const ready = pr(5)
    expect(sortPrs([draft, stuck, waiting, running, ready]).map((p) => p.number)).toEqual([5, 4, 3, 2, 1])
  })
  it('inside needs you, decisions first, then ready to approve, then the rest', () => {
    const ready = pr(1)
    const decisions = pr(2, { decisions: { pending: ['x'], problems: [] } })
    const closed = pr(3, { ticketClosed: true })
    expect(sortPrs([closed, ready, decisions]).map((p) => p.number)).toEqual([2, 1, 3])
  })
  it('same kind: oldest first, so the one to merge first is on top', () => {
    expect(sortPrs([pr(30), pr(10), pr(20)]).map((p) => p.number)).toEqual([10, 20, 30])
  })
  it('same number in two repos: stable by repo', () => {
    const a = pr(5, { repo: 'G-Eskayo/b', key: 'G-Eskayo/b#5' })
    const b = pr(5, { repo: 'G-Eskayo/a', key: 'G-Eskayo/a#5' })
    expect(sortPrs([a, b]).map((p) => p.repo)).toEqual(['G-Eskayo/a', 'G-Eskayo/b'])
  })
  it('does not change the list it was given', () => {
    const list = [pr(2), pr(1)]
    sortPrs(list)
    expect(list.map((p) => p.number)).toEqual([2, 1])
  })
  it('a status for one PR (a merge running) moves only that one', () => {
    const list = [pr(1), pr(2)]
    expect(sortPrs(list, { statusOf: (p) => (p.number === 1 ? 'approving' : 'idle') }).map((p) => p.number)).toEqual([2, 1])
  })
})

describe('groupPrs: one group per project, with a count and what needs you', () => {
  const prs = [
    pr(700),
    pr(701, { decisions: { pending: ['x'], problems: [] } }),
    pr(702, { labels: ['project:portfolio-website-updater'], checks: { state: 'pending', failing: [], pending: ['t'] } }),
    pr(60, { repo: 'G-Eskayo/clarity-captions' }),
    pr(61, { repo: 'G-Eskayo/clarity-captions', isDraft: true }),
    pr(3, { repo: 'stranger/repo' })
  ]
  const groups = groupPrs(prs, PROJECTS)
  it('makes one group per project that has PRs, plus Other', () => {
    expect(groups.map((g) => g.id)).toEqual(['marvin', 'clarity-captions', 'portfolio-website-updater', OTHER])
  })
  it('every PR lands in exactly one group: nothing vanishes', () => {
    expect(groups.flatMap((g) => g.prs.map((p) => p.key)).sort()).toEqual(prs.map((p) => p.key).sort())
  })
  it('names each group from the catalog; Other is "Other"', () => {
    expect(groups.map((g) => g.name)).toEqual(['MARVIN', 'Seal Speak', 'Portfolio', 'Other'])
  })
  it('counts the PRs and the ones that need you', () => {
    const m = groups.find((g) => g.id === 'marvin')
    expect([m.count, m.needsYou]).toEqual([2, 2])
    expect(groups.find((g) => g.id === 'portfolio-website-updater').needsYou).toBe(0)
  })
  it('sorts inside each group', () => {
    expect(groups.find((g) => g.id === 'marvin').prs.map((p) => p.number)).toEqual([701, 700])
    expect(groups.find((g) => g.id === 'clarity-captions').prs.map((p) => p.number)).toEqual([60, 61])
  })
  it('orders groups by what needs you, then by size, then by name; Other always last', () => {
    const g = groupPrs([pr(1, { repo: 'stranger/x' }), pr(1, { repo: 'stranger/y' }), pr(2, { repo: 'G-Eskayo/nourished', isDraft: true }), pr(3, { repo: 'G-Eskayo/marvin-mobile' })], PROJECTS)
    expect(g.map((x) => x.id)).toEqual(['marvin-mobile', 'nourished', OTHER])
  })
  it('a tie on needs-you and size goes by name, so the order does not jump between refreshes', () => {
    const g = groupPrs([pr(1, { repo: 'G-Eskayo/nourished' }), pr(2, { repo: 'G-Eskayo/marvin-mobile' })], PROJECTS)
    expect(g.map((x) => x.name)).toEqual(['MARVIN Mobile', 'nourished'])
  })
  it('Other says why each PR is there', () => {
    const other = groups.find((g) => g.id === OTHER)
    expect(other.prs[0].groupWhy).toBe('unknown-repo')
  })
  it('hides projects with no open PRs by default', () => {
    expect(groups.some((g) => g.id === 'nourished')).toBe(false)
  })
  it('can show them as empty groups at the end instead (an edge-case decision), but only catalog projects with a repo', () => {
    const g = groupPrs([pr(1)], PROJECTS, { empty: 'show' })
    expect(g.map((x) => x.id)).toEqual(['marvin', 'marvin-mobile', 'nourished', 'portfolio-website-updater', 'clarity-captions'])
    expect(g.at(-1).count).toBe(0)
  })
  it('shows only the projects it was told are live when given a filter for empties (archived ones stay out)', () => {
    const g = groupPrs([pr(1)], PROJECTS, { empty: 'show', isLive: (p) => p.id !== 'nourished' })
    expect(g.map((x) => x.id)).not.toContain('nourished')
  })
  it('no PRs, empties hidden: no groups at all', () => {
    expect(groupPrs([], PROJECTS)).toEqual([])
  })
  it('a project whose catalog name is missing falls back to its id', () => {
    const g = groupPrs([pr(1, { repo: 'G-Eskayo/x' })], [{ id: 'x', repo: 'G-Eskayo/x' }])
    expect(g[0].name).toBe('x')
  })
})

describe('allView: today list, kept as it is', () => {
  it('keeps the order MR Review shows today (no re-sort), as the ticket asks', () => {
    const list = [pr(9), pr(3, { repo: 'G-Eskayo/clarity-captions' }), pr(5)]
    expect(allView(list).map((p) => p.number)).toEqual([9, 3, 5])
  })
  it('can use the new sort instead when that is chosen', () => {
    expect(allView([pr(9), pr(5, { isDraft: true }), pr(3)], { sort: true }).map((p) => p.number)).toEqual([3, 9, 5])
  })
})

describe('needsYouSummary: the line a group header shows', () => {
  it('names what needs you', () => {
    const prs = [pr(1), pr(2), pr(3, { decisions: { pending: ['a'], problems: [] } }), pr(4, { ticketClosed: true })]
    expect(needsYouSummary(prs)).toBe('1 decision · 2 to approve · 1 other')
  })
  it('plural decisions', () => {
    expect(needsYouSummary([pr(1, { decisions: { pending: ['a'], problems: [] } }), pr(2, { decisions: { pending: ['b'], problems: [] } })])).toBe('2 decisions')
  })
  it('nothing needs you: says what the PRs are doing instead', () => {
    expect(needsYouSummary([pr(1, { isDraft: true }), pr(2, { checks: { state: 'pending', failing: [], pending: ['t'] } })])).toBe('nothing for you · 1 running · 1 draft')
  })
  it('empty group', () => expect(needsYouSummary([])).toBe('no open MRs'))
})

describe('collapse: per group, remembered; the saved choice beats the default', () => {
  const big = { id: 'marvin', count: 12, needsYou: 0 }
  const small = { id: 'nourished', count: 2, needsYou: 0 }
  const urgent = { id: 'x', count: 12, needsYou: 1 }
  it('default "open": everything starts open', () => {
    expect(isCollapsed(big, {}, { rule: 'open' })).toBe(false)
  })
  it('default "big": groups over the limit start collapsed', () => {
    expect(isCollapsed(big, {}, { rule: 'big', limit: 8 })).toBe(true)
    expect(isCollapsed(small, {}, { rule: 'big', limit: 8 })).toBe(false)
  })
  it('default "quiet": groups with nothing for you start collapsed, however big', () => {
    expect(isCollapsed(small, {}, { rule: 'quiet' })).toBe(true)
    expect(isCollapsed(urgent, {}, { rule: 'quiet' })).toBe(false)
  })
  it('an empty group is always collapsed (nothing to show)', () => {
    expect(isCollapsed({ id: 'e', count: 0, needsYou: 0 }, { e: false }, { rule: 'open' })).toBe(true)
  })
  it('what you chose wins over the default, both ways', () => {
    expect(isCollapsed(big, { marvin: false }, { rule: 'big', limit: 8 })).toBe(false)
    expect(isCollapsed(small, { nourished: true }, { rule: 'open' })).toBe(true)
  })
  it('toggling records the opposite of what is shown, without touching other groups', () => {
    const saved = { other: true }
    const next = toggleCollapsed(saved, big, { rule: 'big', limit: 8 })
    expect(next).toEqual({ other: true, marvin: false })
    expect(saved).toEqual({ other: true })
  })
  it('a choice for a group that later turns urgent is still honoured (you collapsed it on purpose)', () => {
    expect(isCollapsed(urgent, { x: true }, { rule: 'quiet' })).toBe(true)
  })
})

describe('placeValue: one remembered scroll place per view and per focused group (#755)', () => {
  it('All and By project are different places', () => {
    expect(placeValue({ grouping: 'all' })).toBe('all')
    expect(placeValue({ grouping: 'project' })).toBe('project')
  })
  it('a group opened on its own has its own place', () => {
    expect(placeValue({ grouping: 'project', focus: 'clarity-captions' })).toBe('project:clarity-captions')
  })
  it('focus is ignored in All (there are no groups there)', () => {
    expect(placeValue({ grouping: 'all', focus: 'marvin' })).toBe('all')
  })
})

describe('historyItem: a focused group is a step in the one dashboard history (#756)', () => {
  it('the grouped list itself is the tab list (item null)', () => expect(historyItem({ grouping: 'project' })).toBe(null))
  it('a focused group is an item, so swipe back returns to every group', () => {
    expect(historyItem({ grouping: 'project', focus: 'marvin' })).toBe('project:marvin')
  })
  it('All is not a step of its own', () => expect(historyItem({ grouping: 'all', focus: 'marvin' })).toBe(null))
})

describe('diffGroups: what the merge motion (#757) has to animate between two lists', () => {
  const before = groupPrs([pr(1), pr(2, { repo: 'G-Eskayo/nourished' }), pr(3, { checks: { state: 'pending', failing: [], pending: ['t'] } })], PROJECTS)
  it('a merged PR that was its group last leaves with its group', () => {
    const after = groupPrs([pr(1), pr(3, { checks: { state: 'pending', failing: [], pending: ['t'] } })], PROJECTS)
    expect(diffGroups(before, after)).toEqual({ left: [{ key: 'G-Eskayo/nourished#2', group: 'nourished' }], groupsGone: ['nourished'], groupsNew: [], moved: [], reordered: false })
  })
  it('a PR whose checks finished moves up inside its group (so the motion can slide it, not jump)', () => {
    const after = groupPrs([pr(1), pr(2, { repo: 'G-Eskayo/nourished' }), pr(3)], PROJECTS)
    const d = diffGroups(before, after)
    expect(d.moved).toEqual([{ key: 'G-Eskayo/marvin#3', from: { group: 'marvin', tier: 'running' }, to: { group: 'marvin', tier: 'needs-you' } }])
    expect(d.left).toEqual([])
  })
  it('a newly labelled PR moves to another group', () => {
    const after = groupPrs([pr(1, { labels: ['project:marvin-mobile'] }), pr(2, { repo: 'G-Eskayo/nourished' }), pr(3, { checks: { state: 'pending', failing: [], pending: ['t'] } })], PROJECTS)
    const d = diffGroups(before, after)
    expect(d.moved).toEqual([{ key: 'G-Eskayo/marvin#1', from: { group: 'marvin', tier: 'needs-you' }, to: { group: 'marvin-mobile', tier: 'needs-you' } }])
    expect(d.groupsNew).toEqual(['marvin-mobile'])
  })
  it('says when the group order itself changed', () => {
    const after = groupPrs([pr(2, { repo: 'G-Eskayo/nourished' }), pr(3, { checks: { state: 'pending', failing: [], pending: ['t'] } })], PROJECTS)
    expect(diffGroups(before, after).reordered).toBe(true)
  })
  it('nothing changed: nothing to animate', () => {
    expect(diffGroups(before, before)).toEqual({ left: [], groupsGone: [], groupsNew: [], moved: [], reordered: false })
  })
})

describe('helperFor: which helper tab owns a PR, by the helper-tab title (marvin#753)', () => {
  const tabs = [
    { state: 'running', group: 'Seal Speak', title: '#60 split wiring' },
    { state: 'done', group: 'MARVIN', title: '#758 MR Review by project' },
    { state: 'running', group: 'MARVIN', title: 'cleanup' }
  ]
  it('matches the ticket a PR closes, inside the same project group', () => {
    const p = pr(761, { ticketRef: 758 })
    expect(helperFor(p, 'MARVIN', tabs)).toEqual({ state: 'done', label: '✓ MARVIN · #758 MR Review by project' })
  })
  it('matches the PR number too', () => {
    expect(helperFor(pr(60, { repo: 'G-Eskayo/clarity-captions' }), 'Seal Speak', tabs).state).toBe('running')
  })
  it('the same number in another project is not a match (numbers repeat across repos)', () => {
    expect(helperFor(pr(60), 'MARVIN', tabs)).toBe(null)
  })
  it('#7 does not match #758', () => {
    expect(helperFor(pr(7), 'MARVIN', tabs)).toBe(null)
  })
  it('the group name match ignores case and spacing', () => {
    expect(helperFor(pr(60, { repo: 'G-Eskayo/clarity-captions' }), 'seal  speak', tabs)).not.toBe(null)
  })
  it('several tabs for one PR: a running one wins over a finished one', () => {
    const t = [{ state: 'failed', group: 'MARVIN', title: '#9 first try' }, { state: 'running', group: 'MARVIN', title: '#9 second try' }]
    expect(helperFor(pr(9), 'MARVIN', t).label).toBe('● MARVIN · #9 second try')
  })
  it('no tabs (WezTerm not running): no owner shown', () => {
    expect(helperFor(pr(9), 'MARVIN', null)).toBe(null)
  })
})
