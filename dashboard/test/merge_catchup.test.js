import { describe, it, expect, vi } from 'vitest'
import { catchUpOne, catchUpMerges } from '../electron/main/merge_catchup.js'
import { createMergeOps } from '../electron/main/merge_ops.js'

const PR = 'https://github.com/G-Eskayo/marvin/pull/559'

describe('catchUpOne: fetch and adopt a single merge from a remote webhook', () => {
  it('fetches progress from /merge-progress?url=PR, adopts it into mergeOps, and pushes', async () => {
    const progress = { id: 'a1', seq: 5, stages: { queued: { state: 'done' }, tests: { state: 'running' } } }
    const fp = vi.fn(async () => progress)
    const mergeOps = createMergeOps()
    const pushed = []
    mergeOps.start(PR, Date.now(), 'old-head')
    const op = await catchUpOne(PR, { webhookUrl: 'http://localhost:7878/approve', mergeOps, fetchProgress: fp, push: (url, o) => pushed.push({ url, op: o }) })
    expect(fp).toHaveBeenCalledWith(expect.stringContaining('/merge-progress'))
    expect(fp).toHaveBeenCalledWith(expect.stringContaining('559'))
    expect(op.state).toBe('merging')
    expect(pushed).toHaveLength(1)
  })

  it('returns null if fetch fails', async () => {
    const fp = vi.fn(async () => { throw new Error('unreachable') })
    const mergeOps = createMergeOps()
    const op = await catchUpOne(PR, { webhookUrl: 'http://localhost:7878/approve', mergeOps, fetchProgress: fp, push: () => {} })
    expect(op).toBe(null)
  })

  it('returns null if no progress is returned', async () => {
    const fp = vi.fn(async () => null)
    const mergeOps = createMergeOps()
    const op = await catchUpOne(PR, { webhookUrl: 'http://localhost:7878/approve', mergeOps, fetchProgress: fp, push: () => {} })
    expect(op).toBe(null)
  })

  it('returns null if no webhookUrl', async () => {
    const fp = vi.fn()
    const mergeOps = createMergeOps()
    const op = await catchUpOne(PR, { mergeOps, fetchProgress: fp, push: () => {} })
    expect(op).toBe(null)
    expect(fp).not.toHaveBeenCalled()
  })

  it('push that throws does not break catchup', async () => {
    const progress = { id: 'a1', seq: 1, stages: { queued: { state: 'running' } } }
    const fp = vi.fn(async () => progress)
    const mergeOps = createMergeOps()
    mergeOps.start(PR, Date.now())
    const op = await catchUpOne(PR, { webhookUrl: 'http://localhost:7878/approve', mergeOps, fetchProgress: fp, push: () => { throw new Error('boom') } })
    expect(op.state).toBe('merging')
  })
})

describe('catchUpMerges: catch up multiple PRs in parallel', () => {
  it('catches up each PR, returning the ones that succeeded', async () => {
    const progress1 = { id: 'a1', seq: 1, stages: { queued: { state: 'running' } } }
    const progress2 = { id: 'a2', seq: 2, stages: { queued: { state: 'running' } } }
    const fp = vi.fn(async (url) => {
      if (url.includes('559')) return progress1
      if (url.includes('560')) return progress2
      throw new Error('unknown')
    })
    const mergeOps = createMergeOps()
    const pr1 = 'https://github.com/G-Eskayo/marvin/pull/559'
    const pr2 = 'https://github.com/G-Eskayo/marvin/pull/560'
    const pr3 = 'https://github.com/G-Eskayo/marvin/pull/561'
    mergeOps.start(pr1, Date.now())
    mergeOps.start(pr2, Date.now())
    mergeOps.start(pr3, Date.now())
    const caught = await catchUpMerges([pr1, pr2, pr3], { webhookUrl: 'http://localhost:7878/approve', mergeOps, fetchProgress: fp, push: () => {} })
    expect(caught).toEqual([pr1, pr2])
    expect(mergeOps.get(pr1).state).toBe('merging')
    expect(mergeOps.get(pr2).state).toBe('merging')
    expect(mergeOps.get(pr3).state).toBe('merging')
  })

  it('empty list returns empty', async () => {
    const fp = vi.fn()
    const mergeOps = createMergeOps()
    const caught = await catchUpMerges([], { webhookUrl: 'http://localhost:7878/approve', mergeOps, fetchProgress: fp, push: () => {} })
    expect(caught).toEqual([])
    expect(fp).not.toHaveBeenCalled()
  })
})
