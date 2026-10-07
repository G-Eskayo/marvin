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
