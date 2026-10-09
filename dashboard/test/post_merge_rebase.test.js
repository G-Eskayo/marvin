import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { rebaseOpenPrs, conflictFiles } from '../webhook-server/post_merge_rebase.js'
import { readRebaseStatus, writeRebaseStatus } from '../webhook-server/rebase_status.js'

// #225: after every merge, the remaining open PRs are rebased onto the new main by code (no LLM), so a conflict or a
// red test shows on MR Review before anyone presses Approve.
const REPO = 'G-Eskayo/marvin'
const MERGED = 'https://github.com/G-Eskayo/marvin/pull/229'
const pr = (n, ticket, extra = {}) => ({ number: n, url: `https://github.com/${REPO}/pull/${n}`, headRefName: `ticket/${ticket}-x`,
  baseRefName: 'main', isCrossRepository: false, body: `Closes ${REPO}#${ticket}`, ...extra })
const listing = (prs) => vi.fn(async (cmd, args) => {
  if (cmd === 'gh' && args[0] === 'pr' && args[1] === 'list') return { stdout: JSON.stringify(prs), stderr: '' }
  throw new Error(`unexpected ${cmd} ${args.join(' ')}`)
})
const NOW = () => new Date('2026-10-07T22:00:00.000Z')

function run(prs, rebase, extra = {}) {
  const recordStageFn = vi.fn()
  const writeStatus = vi.fn()
  const p = rebaseOpenPrs({ repo: REPO, mergedPrUrl: MERGED, exec: listing(prs), rebase, recordStageFn, writeStatus, now: NOW, ...extra })
  return p.then((entries) => ({ entries, recordStageFn, writeStatus }))
}

describe('rebaseOpenPrs', () => {
  it('rebases every other open PR on the base branch, one at a time, and records each as clean', async () => {
    const order = []
    let running = 0
    const rebase = vi.fn(async (head) => {
      running++
      expect(running).toBe(1)
      order.push(head)
      await new Promise((r) => setTimeout(r, 5))
      running--
      return { ok: true }
    })
    const { entries, recordStageFn, writeStatus } = await run(
      [pr(229, 215), pr(208, 161), pr(210, 159), pr(240, 1, { baseRefName: 'side' }), pr(241, 2, { isCrossRepository: true })], rebase)
    expect(order).toEqual(['ticket/161-x', 'ticket/159-x'])
    expect(entries.map((e) => [e.pr, e.state])).toEqual([[208, 'clean'], [210, 'clean']])
    expect(recordStageFn).toHaveBeenCalledWith(161, 'gate', 'passed', 'rebased onto main after PR #229 merged', { repo: REPO })
    expect(writeStatus).toHaveBeenCalledWith(entries)
    expect(entries[0]).toMatchObject({ url: `https://github.com/${REPO}/pull/208`, after: 229, at: '2026-10-07T22:00:00.000Z', files: [] })
  })

  it('a real conflict is recorded with its files and the PR is left alone (not sent back here)', async () => {
    const rebase = vi.fn(async () => ({ ok: false, reason: 'Rebase onto main failed:\n\nCONFLICT (content): Merge conflict in dashboard/mobile-backend/index.js\nerror: could not apply abc' }))
    const { entries, recordStageFn } = await run([pr(208, 161)], rebase)
    expect(entries[0]).toMatchObject({ state: 'conflict', files: ['dashboard/mobile-backend/index.js'] })
    expect(recordStageFn).toHaveBeenCalledWith(161, 'gate', 'failed', 'REBASE_CONFLICT after PR #229 merged: dashboard/mobile-backend/index.js', { repo: REPO })
  })

  it('tests failing after a clean rebase are recorded as tests_failed', async () => {
    const rebase = vi.fn(async () => ({ ok: false, reason: 'Tests failed after rebasing onto main:\n\nFAIL test/x.test.js' }))
    const { entries, recordStageFn } = await run([pr(208, 161)], rebase)
    expect(entries[0].state).toBe('tests_failed')
    expect(recordStageFn).toHaveBeenCalledWith(161, 'gate', 'failed', 'tests fail after rebasing onto main (PR #229 merged)', { repo: REPO })
  })

  it('one PR blowing up does not stop the others', async () => {
    const rebase = vi.fn().mockRejectedValueOnce(new Error('git exploded')).mockResolvedValueOnce({ ok: true })
    const { entries } = await run([pr(208, 161), pr(210, 159)], rebase)
    expect(entries.map((e) => e.state)).toEqual(['error', 'clean'])
  })

  it('a failing PR list means nothing to do, not a crash', async () => {
    const exec = vi.fn(async () => { throw new Error('gh down') })
    const entries = await rebaseOpenPrs({ repo: REPO, mergedPrUrl: MERGED, exec, rebase: vi.fn(), recordStageFn: vi.fn(), writeStatus: vi.fn() })
    expect(entries).toEqual([])
  })

  it('a PR with no linked ticket is still rebased, with no stage-log entry', async () => {
    const { entries, recordStageFn } = await run([pr(208, 161, { body: 'no ticket here' })], vi.fn(async () => ({ ok: true })))
    expect(entries[0].state).toBe('clean')
    expect(recordStageFn).not.toHaveBeenCalled()
  })
})

describe('conflictFiles', () => {
  it('reads every conflicted path from git\'s rebase output', () => {
    expect(conflictFiles('CONFLICT (content): Merge conflict in a.js\nCONFLICT (add/add): Merge conflict in b/c.py\n')).toEqual(['a.js', 'b/c.py'])
  })
})

describe('rebase status store', () => {
  it('keeps the latest result per PR and drops results older than a week', () => {
    const dir = mkdtempSync(path.join(tmpdir(), 'rebase-status-'))
    const file = path.join(dir, 's.json')
    try {
      writeRebaseStatus([{ url: 'u1', state: 'conflict', at: '2026-09-01T00:00:00.000Z' }, { url: 'u2', state: 'clean', at: '2026-10-07T00:00:00.000Z' }], file, NOW)
      writeRebaseStatus([{ url: 'u2', state: 'tests_failed', at: '2026-10-07T21:00:00.000Z' }], file, NOW)
      expect(readRebaseStatus(file)).toEqual({ u2: { url: 'u2', state: 'tests_failed', at: '2026-10-07T21:00:00.000Z' } })
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('reads a missing or corrupt file as empty', () => {
    expect(readRebaseStatus('/nonexistent/s.json')).toEqual({})
  })

  it('a PR stacked on the merged one is moved onto main and then rebased, so its work cannot miss main', async () => {
    const calls = []
    const exec = vi.fn(async (cmd, args) => {
      calls.push(args.join(' '))
      if (args[0] === 'pr' && args[1] === 'view') return { stdout: JSON.stringify({ headRefName: 'ticket/215-parent' }), stderr: '' }
      if (args[0] === 'pr' && args[1] === 'list') {
        return { stdout: JSON.stringify([pr(230, 216, { baseRefName: 'ticket/215-parent' }), pr(231, 217, { baseRefName: 'ticket/999-other' })]), stderr: '' }
      }
      if (args[0] === 'pr' && args[1] === 'edit') return { stdout: '', stderr: '' }
      throw new Error(`unexpected ${args.join(' ')}`)
    })
    const rebase = vi.fn(async () => ({ ok: true }))
    const entries = await rebaseOpenPrs({ repo: REPO, mergedPrUrl: MERGED, exec, rebase, recordStageFn: vi.fn(), writeStatus: vi.fn(), now: NOW })
    expect(calls).toContain(`pr edit https://github.com/${REPO}/pull/230 --base main`)
    expect(calls.some((c) => c.includes('pull/231 --base'))).toBe(false)  // stacked on something else: left alone
    expect(rebase).toHaveBeenCalledWith('ticket/216-x')
    expect(entries).toEqual([expect.objectContaining({ pr: 230, state: 'clean', retargetedFrom: 'ticket/215-parent' })])
  })

  it('a retarget GitHub refuses leaves the PR stacked and says so', async () => {
    const exec = vi.fn(async (cmd, args) => {
      if (args[1] === 'view') return { stdout: JSON.stringify({ headRefName: 'ticket/215-parent' }), stderr: '' }
      if (args[1] === 'list') return { stdout: JSON.stringify([pr(230, 216, { baseRefName: 'ticket/215-parent' })]), stderr: '' }
      throw new Error('HTTP 422')
    })
    const rebase = vi.fn(async () => ({ ok: true }))
    const entries = await rebaseOpenPrs({ repo: REPO, mergedPrUrl: MERGED, exec, rebase, recordStageFn: vi.fn(), writeStatus: vi.fn(), now: NOW })
    expect(rebase).not.toHaveBeenCalled()
    expect(entries).toEqual([expect.objectContaining({ pr: 230, state: 'error', reason: expect.stringContaining('couldn\'t move it onto main') })])
  })
})
