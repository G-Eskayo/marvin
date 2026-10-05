import { describe, it, expect } from 'vitest'
import { waitingOn, assertInOrder } from '../electron/main/pr_order.js'

const pr = (number, files, repo = 'o/r') => ({ number, repo, url: `https://github.com/${repo}/pull/${number}`, title: `PR ${number}`, files: files.map((path) => ({ path })) })

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
