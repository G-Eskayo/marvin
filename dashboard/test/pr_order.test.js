import { describe, it, expect } from 'vitest'
import { waitingOn, assertInOrder } from '../electron/main/pr_order.js'
import { prsForOrderCheck } from '../electron/main/mr_review.js'

const pr = (number, files, repo = 'o/r') => ({ number, repo, url: `https://github.com/${repo}/pull/${number}`, title: `PR ${number}`, files: files.map((path) => ({ path })) })

describe('waitingOn: an older PR that cannot merge does not hold up the newer ones', () => {
  it('skips an older PR that conflicts with main (it will be rebuilt on top of whatever lands first)', () => {
    const older = { ...pr(62, ['a.swift']), mergeable: 'CONFLICTING' }
    const newer = pr(63, ['a.swift'])
    expect(waitingOn([older, newer], newer)).toEqual([])
  })
  it('skips an older PR whose ticket was sent back for rework', () => {
    const older = { ...pr(62, ['a.swift']), sentBack: true }
    const newer = pr(63, ['a.swift'])
    expect(waitingOn([older, newer], newer)).toEqual([])
  })
  it('still waits on an older PR that is mergeable', () => {
    const older = { ...pr(62, ['a.swift']), mergeable: 'MERGEABLE' }
    const newer = pr(63, ['a.swift'])
    expect(waitingOn([older, newer], newer).map((x) => x.number)).toEqual([62])
  })
})

describe('waitingOn: merge older PRs that touch the same files first', () => {
  const prs = [pr(28, ['a.swift', 'n.md']), pr(29, ['b.swift', 'Package.resolved']), pr(30, ['b.swift', 'Package.resolved', 'c.swift']), pr(31, ['Package.resolved'])]
  it('a PR with no overlap with an older one waits on nothing', () => {
    expect(waitingOn(prs, prs[0])).toEqual([])
    expect(waitingOn(prs, prs[1])).toEqual([])
  })
  it('lists each older overlapping PR and the files they share', () => {
    const w = waitingOn(prs, prs[2])
    expect(w.map((x) => x.number)).toEqual([29])
    expect(w[0].shared).toEqual(['Package.resolved', 'b.swift'])
    expect(waitingOn(prs, prs[3]).map((x) => x.number)).toEqual([29, 30])
  })
  it('never waits on a newer PR, nor on another repo', () => {
    expect(waitingOn([pr(1, ['x']), pr(2, ['x'], 'o/other')], pr(2, ['x'], 'o/other'))).toEqual([])
    expect(waitingOn([pr(5, ['x']), pr(4, ['x'])], pr(4, ['x']))).toEqual([])
  })
  it('a PR whose file list is unknown is not blocked on a guess', () => {
    expect(waitingOn([pr(1, ['x']), { number: 2, repo: 'o/r', url: 'u' }], { number: 2, repo: 'o/r', url: 'u' })).toEqual([])
  })
})

describe('assertInOrder', () => {
  const prs = [pr(29, ['x']), pr(30, ['x'])]
  it('throws a message naming what to merge first', () => {
    expect(() => assertInOrder(prs, prs[1].url)).toThrow(/merge #29 first/i)
  })
  it('passes for the head of the line and for a PR that is not listed', () => {
    expect(() => assertInOrder(prs, prs[0].url)).not.toThrow()
    expect(() => assertInOrder(prs, 'https://github.com/o/r/pull/99')).not.toThrow()
  })
})

import { listPipelinePrs } from '../electron/main/mr_review.js'
describe('the MR list carries the order', () => {
  it('each listed PR says what it waits on', async () => {
    const raw = [{ ...pr(29, ['x']), body: '', repo: 'o/r' }, { ...pr(30, ['x']), body: '', repo: 'o/r' }]
    const list = await listPipelinePrs(async () => raw)
    expect(list[0].waitingOn).toEqual([])
    expect(list[1].waitingOn.map((w) => w.number)).toEqual([29])
  })
})

import { baseProblem } from '../electron/main/pr_order.js'
describe('baseProblem: a PR must target the base branch', () => {
  const p = (number, base, head) => ({ number, repo: 'o/r', title: 'T' + number, url: 'u' + number, baseRefName: base, headRefName: head })
  it('is null when it targets the base branch (or the base is unknown)', () => {
    expect(baseProblem([p(1, 'main', 'a')], p(1, 'main', 'a'))).toBeNull()
    expect(baseProblem([], { number: 2, repo: 'o/r' })).toBeNull()
  })
  it('names the parent PR when the base is another open PR\'s branch (a stack)', () => {
    const prs = [p(7, 'main', 'feature/a'), p(8, 'feature/a', 'feature/b')]
    expect(baseProblem(prs, prs[1])).toMatchObject({ base: 'feature/a', parent: { number: 7 } })
  })
  it('has no parent when the base branch has no open PR (the parent already merged, or never existed)', () => {
    const r = baseProblem([p(8, 'feature/a', 'feature/b')], p(8, 'feature/a', 'feature/b'))
    expect(r.base).toBe('feature/a')
    expect(r.parent).toBeNull()
  })
  it('assertInOrder refuses it with the reason', () => {
    const prs = [p(7, 'main', 'feature/a'), p(8, 'feature/a', 'feature/b')]
    expect(() => assertInOrder(prs, 'u8')).toThrow(/targets "feature\/a", not main/)
    expect(() => assertInOrder(prs, 'u8')).toThrow(/#7/)
  })
  it('the MR list carries it', async () => {
    const raw = [{ ...p(8, 'feature/a', 'feature/b'), body: '', files: [] }]
    expect((await listPipelinePrs(async () => raw))[0].baseProblem).toMatchObject({ base: 'feature/a' })
  })
})

describe('conflicts are visible before anyone clicks Approve', () => {
  it('the MR list carries GitHub\'s mergeable verdict', async () => {
    const raw = [{ ...pr(48, ['x']), body: '', repo: 'o/r', mergeable: 'CONFLICTING' }, { ...pr(49, ['y']), body: '', repo: 'o/r', mergeable: 'MERGEABLE' }]
    const list = await listPipelinePrs(async () => raw)
    expect(list.map((p) => p.conflicts)).toEqual([true, false])
  })
  it('UNKNOWN (GitHub has not computed it yet) is not treated as a conflict', async () => {
    const list = await listPipelinePrs(async () => [{ ...pr(1, ['x']), body: '', repo: 'o/r', mergeable: 'UNKNOWN' }])
    expect(list[0].conflicts).toBe(false)
  })
})

describe('the MR list shows each PR\'s CI state', () => {
  const chk = (n, status, conclusion) => ({ __typename: 'CheckRun', name: n, status, conclusion })
  it('carries passing / failing / pending / none from GitHub\'s checks', async () => {
    const raw = [
      { ...pr(1, ['a']), body: '', repo: 'o/r', statusCheckRollup: [chk('t', 'COMPLETED', 'SUCCESS')] },
      { ...pr(2, ['b']), body: '', repo: 'o/r', statusCheckRollup: [chk('t', 'COMPLETED', 'FAILURE')] },
      { ...pr(3, ['c']), body: '', repo: 'o/r', statusCheckRollup: [chk('t', 'IN_PROGRESS', null)] },
      { ...pr(4, ['d']), body: '', repo: 'o/r', statusCheckRollup: [] }
    ]
    const list = await listPipelinePrs(async () => raw)
    expect(list.map((p) => p.checks.state)).toEqual(['passing', 'failing', 'pending', 'none'])
    expect(list[1].checks.failing).toEqual(['t'])
  })
})

// marvin #209 (2026-10-07): the review list skipped sent-back PR #208, but the check run on the Approve click got the
// raw PR list (no `sentBack` field), so #209 was refused with "Merge #208 first" while #208 was refused as sent back.
describe('prsForOrderCheck: the Approve-time order check sees sent-back PRs the same way the list does', () => {
  const raw = () => [
    { ...pr(208, ['mobile-backend/index.js'], 'G-Eskayo/marvin'), body: 'Closes G-Eskayo/marvin#161', mergeable: 'UNKNOWN' },
    { ...pr(209, ['mobile-backend/index.js'], 'G-Eskayo/marvin'), body: 'Closes G-Eskayo/marvin#158', mergeable: 'MERGEABLE' }
  ]
  it('a newer PR is not held up by an older one whose ticket was sent back', async () => {
    const prs = await prsForOrderCheck(raw(), async () => new Set(['G-Eskayo/marvin#161']))
    expect(() => assertInOrder(prs, 'https://github.com/G-Eskayo/marvin/pull/209')).not.toThrow()
  })
  it('still waits on the older PR when its ticket was not sent back', async () => {
    const prs = await prsForOrderCheck(raw(), async () => new Set())
    expect(() => assertInOrder(prs, 'https://github.com/G-Eskayo/marvin/pull/209')).toThrow(/Merge #208 first/)
  })
  it('a failing sent-back lookup falls back to the plain order check rather than throwing', async () => {
    const prs = await prsForOrderCheck(raw(), async () => { throw new Error('gh down') })
    expect(() => assertInOrder(prs, 'https://github.com/G-Eskayo/marvin/pull/209')).toThrow(/Merge #208 first/)
  })
})

// 2026-10-09: one PR missing screenshots (#358) held every newer PR touching index.js hostage -- #378, #371 and #389 sat
// greyed out "waiting for #358" while #358 itself could never be approved until someone added images. An older PR that
// is stuck on its own (no images, a vague ask, open decisions, failing checks, wrong base) is skipped like a conflict is.
describe('waitingOn: an older PR stuck on its own blocker does not hold up the newer ones', () => {
  it('skips an older PR marked blocked', () => {
    const older = { ...pr(358, ['dashboard/electron/main/index.js']), blocked: 'needs images' }
    const newer = pr(378, ['dashboard/electron/main/index.js'])
    expect(waitingOn([older, newer], newer)).toEqual([])
  })
  it('still waits on an older PR that is only waiting for its checks (it will be approvable soon)', () => {
    const older = { ...pr(10, ['a.js']), blocked: null }
    expect(waitingOn([older, pr(11, ['a.js'])], pr(11, ['a.js'])).map((x) => x.number)).toEqual([10])
  })
  it('a chain unjams: 388 -> 363 -> 362, with 362 blocked, 388 waits only on 363', () => {
    const prs = [{ ...pr(362, ['CONTEXT.md']), blocked: 'needs images' }, pr(363, ['CONTEXT.md', 'lib/ticket_pipeline.py']), pr(388, ['lib/ticket_pipeline.py'])]
    expect(waitingOn(prs, prs[1])).toEqual([])
    expect(waitingOn(prs, prs[2]).map((x) => x.number)).toEqual([363])
  })
  it('the merge gate agrees: assertInOrder lets the newer one through', () => {
    const older = { ...pr(358, ['x.js']), blocked: 'needs images' }
    const newer = pr(378, ['x.js'])
    expect(() => assertInOrder([older, newer], newer.url)).not.toThrow()
  })
})

describe('prsForOrderCheck marks PRs stuck on their own, so the Approve click agrees with the card', () => {
  const ui = (n, files, body = 'no pictures', extra = {}) => ({ ...pr(n, files), body, ...extra })
  it('a UI change without images is blocked; with an image it is not', async () => {
    const [a, b] = await prsForOrderCheck([ui(1, ['dashboard/src/components/X.jsx']), ui(2, ['dashboard/src/components/X.jsx'], '![s](https://x/y.png)')], async () => new Set())
    expect(a.blocked).toMatch(/images/)
    expect(b.blocked).toBeNull()
  })
  it('failing checks, a vague ask and open decisions block; pending checks do not', async () => {
    const failing = ui(1, ['lib/a.py'], 'x', { statusCheckRollup: [{ name: 't', status: 'COMPLETED', conclusion: 'FAILURE' }] })
    const pending = ui(2, ['lib/a.py'], 'x', { statusCheckRollup: [{ name: 't', status: 'IN_PROGRESS', conclusion: null }] })
    const vague = ui(3, ['lib/a.py'], '## Open questions\n\nShould we use A or B?')
    const out = await prsForOrderCheck([failing, pending, vague], async () => new Set())
    expect(out[0].blocked).toMatch(/checks/)
    expect(out[1].blocked).toBeNull()
    expect(out[2].blocked).toBeTruthy()
  })
  it('a PR whose files are unknown is never marked blocked (fails closed: it is still waited on)', async () => {
    const [a] = await prsForOrderCheck([{ number: 1, repo: 'o/r', url: 'u', body: 'none' }], async () => new Set())
    expect(a.blocked).toBeNull()
  })
  it('uses the project\'s own UI paths', async () => {
    const p = ui(1, ['Apps/Main/Home.swift'])
    const [plain] = await prsForOrderCheck([p], async () => new Set())
    const [own] = await prsForOrderCheck([p], async () => new Set(), () => ['Apps/**/*.swift'])
    expect(plain.blocked).toBeNull()
    expect(own.blocked).toMatch(/images/)
  })
})
