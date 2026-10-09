import { describe, it, expect, vi } from 'vitest'
import { orphanedStacks, createStackRetarget } from '../electron/main/stack_retarget.js'

const R = 'G-Eskayo/marvin'
const pr = (n, head, base = 'main', repo = R) => ({ number: n, url: `https://github.com/${repo}/pull/${n}`, headRefName: head, baseRefName: base, repo })

describe('orphanedStacks: PRs whose parent PR is no longer open', () => {
  it('finds a PR stacked on a branch no open PR owns, and leaves a live stack alone', () => {
    const prs = [pr(312, 'b-312', 'b-309'), pr(313, 'b-313', 'b-312'), pr(320, 'b-320')]
    expect(orphanedStacks(prs).map((p) => p.number)).toEqual([312])
  })

  it('compares within a repo only', () => {
    const prs = [pr(5, 'x', 'parent', 'o/a'), pr(6, 'parent', 'main', 'o/b')]
    expect(orphanedStacks(prs).map((p) => p.number)).toEqual([5])
  })
})

describe('createStackRetarget: the safety net for a missed post-merge move', () => {
  const gh = (merged) => vi.fn(async (args) => {
    if (args[0] === 'pr' && args[1] === 'list') return JSON.stringify(merged ? [{ number: 309 }] : [])
    if (args[0] === 'pr' && args[1] === 'edit') return ''
    throw new Error(`unexpected ${args.join(' ')}`)
  })

  it('moves a PR onto main when its parent merged, and says what it did', async () => {
    const g = gh(true)
    const onMoved = vi.fn()
    const net = createStackRetarget({ gh: g, onMoved, now: () => 0 })
    const moved = await net.check([pr(312, 'b-312', 'b-309')])
    expect(g).toHaveBeenCalledWith(['pr', 'list', '--repo', R, '--state', 'merged', '--head', 'b-309', '--limit', '1', '--json', 'number'])
    expect(g).toHaveBeenCalledWith(['pr', 'edit', 'https://github.com/G-Eskayo/marvin/pull/312', '--base', 'main'])
    expect(moved).toEqual([{ repo: R, number: 312, from: 'b-309', parent: 309 }])
    expect(onMoved).toHaveBeenCalledWith(moved)
  })

  it('a parent closed without merging is left alone: moving it would drag unmerged work along', async () => {
    const g = gh(false)
    const net = createStackRetarget({ gh: g, now: () => 0 })
    expect(await net.check([pr(312, 'b-312', 'b-309')])).toEqual([])
    expect(g).not.toHaveBeenCalledWith(expect.arrayContaining(['edit']))
  })

  it('asks GitHub about the same PR at most every 5 minutes', async () => {
    let t = 0
    const g = gh(false)
    const net = createStackRetarget({ gh: g, now: () => t })
    await net.check([pr(312, 'b-312', 'b-309')])
    await net.check([pr(312, 'b-312', 'b-309')])
    expect(g).toHaveBeenCalledTimes(1)
    t += 5 * 60_000 + 1
    await net.check([pr(312, 'b-312', 'b-309')])
    expect(g).toHaveBeenCalledTimes(2)
  })

  it('nothing orphaned costs no GitHub calls', async () => {
    const g = gh(true)
    await createStackRetarget({ gh: g }).check([pr(1, 'a'), pr(2, 'b', 'a')])
    expect(g).not.toHaveBeenCalled()
  })

  it('a GitHub failure is reported, never thrown', async () => {
    const log = vi.fn()
    const net = createStackRetarget({ gh: vi.fn(async () => { throw new Error('rate limit') }), log, now: () => 0 })
    expect(await net.check([pr(312, 'b-312', 'b-309')])).toEqual([])
    expect(log).toHaveBeenCalledWith(expect.stringMatching(/312.*rate limit/))
  })
})
