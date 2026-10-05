import { describe, it, expect } from 'vitest'
import { createMergeOps } from '../electron/main/merge_ops.js'

const URL = 'https://github.com/o/r/pull/5'

describe('merge ops (survives the renderer navigating away)', () => {
  it('is idle until a merge starts, merging while it runs', () => {
    const ops = createMergeOps()
    expect(ops.get(URL)).toEqual({ state: 'idle' })
    ops.start(URL)
    expect(ops.get(URL).state).toBe('merging')
  })

  it('remembers a re-engagement or failure so the message is still there on return', () => {
    const ops = createMergeOps()
    ops.start(URL)
    ops.finish(URL, { reengaged: true, reason: 'rebase conflict' })
    expect(ops.get(URL)).toMatchObject({ state: 'reengaged', reason: 'rebase conflict' })
    ops.start(URL)
    ops.fail(URL, 'webhook down')
    expect(ops.get(URL)).toMatchObject({ state: 'error', reason: 'webhook down' })
  })

  it('a merged or cancelled attempt leaves nothing behind', () => {
    const ops = createMergeOps()
    ops.start(URL); ops.finish(URL, { merged: true })
    expect(ops.get(URL)).toEqual({ state: 'idle' })
    ops.start(URL); ops.cancel(URL)
    expect(ops.get(URL)).toEqual({ state: 'idle' })
  })

  it('refuses a second concurrent start for the same PR (double click, or a second window)', () => {
    const ops = createMergeOps()
    expect(ops.start(URL)).toBe(true)
    expect(ops.start(URL)).toBe(false)
  })

  it('tracks PRs independently', () => {
    const ops = createMergeOps()
    ops.start(URL)
    expect(ops.get('https://github.com/o/r/pull/6').state).toBe('idle')
  })
})
