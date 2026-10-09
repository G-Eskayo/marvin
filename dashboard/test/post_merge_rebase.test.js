import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { checkOpenPrs } from '../webhook-server/post_merge_rebase.js'
import { readRebaseStatus, writeRebaseStatus } from '../webhook-server/rebase_status.js'

// #225 (overlap rule): after every merge, the remaining open PRs are conflict-checked against the new main (no tests,
// no pushes), so a conflict shows on MR Review before anyone presses Approve.
const REPO = 'G-Eskayo/marvin'
const MERGED = 'https://github.com/G-Eskayo/marvin/pull/229'
const pr = (n, ticket, extra = {}) => ({ number: n, url: `https://github.com/${REPO}/pull/${n}`, headRefName: `ticket/${ticket}-x`,
  baseRefName: 'main', isCrossRepository: false, body: `Closes ${REPO}#${ticket}`, ...extra })
const listing = (prs) => vi.fn(async (cmd, args) => {
  if (cmd === 'gh' && args[0] === 'pr' && args[1] === 'list') return { stdout: JSON.stringify(prs), stderr: '' }
  throw new Error(`unexpected ${cmd} ${args.join(' ')}`)
})
const NOW = () => new Date('2026-10-07T22:00:00.000Z')

function run(prs, check, extra = {}) {
  const recordStageFn = vi.fn()
  const writeStatus = vi.fn()
  const p = checkOpenPrs({ repo: REPO, mergedPrUrl: MERGED, exec: listing(prs), check, recordStageFn, writeStatus, now: NOW, ...extra })
  return p.then((entries) => ({ entries, recordStageFn, writeStatus }))
}

describe('checkOpenPrs', () => {
  it('conflict-checks every other open PR on the base branch, one at a time, with no tests and no pushes', async () => {
    const order = []
    let running = 0
    const check = vi.fn(async (head) => {
      running++
      expect(running).toBe(1)
      order.push(head)
      await new Promise((r) => setTimeout(r, 5))
      running--
      return { conflict: false, files: [] }
    })
    const { entries, recordStageFn, writeStatus } = await run(
      [pr(229, 215), pr(208, 161), pr(210, 159), pr(240, 1, { baseRefName: 'side' }), pr(241, 2, { isCrossRepository: true })], check)
    expect(order).toEqual(['ticket/161-x', 'ticket/159-x'])
    expect(entries.map((e) => [e.pr, e.state])).toEqual([[208, 'clean'], [210, 'clean']])
    expect(recordStageFn).not.toHaveBeenCalled()  // "still merges" is not a test result, so no gate pass on the timeline
    expect(writeStatus).toHaveBeenCalledWith(entries)
    expect(entries[0]).toMatchObject({ url: `https://github.com/${REPO}/pull/208`, after: 229, at: '2026-10-07T22:00:00.000Z', files: [] })
  })

  it('a conflict is recorded with its files and goes on the ticket timeline (the PR is not sent back here)', async () => {
    const check = vi.fn(async () => ({ conflict: true, files: ['dashboard/mobile-backend/index.js'] }))
    const { entries, recordStageFn } = await run([pr(208, 161)], check)
    expect(entries[0]).toMatchObject({ state: 'conflict', files: ['dashboard/mobile-backend/index.js'] })
    expect(recordStageFn).toHaveBeenCalledWith(161, 'gate', 'failed', 'REBASE_CONFLICT after PR #229 merged: dashboard/mobile-backend/index.js', { repo: REPO })
  })

  it('one PR blowing up does not stop the others', async () => {
    const check = vi.fn().mockRejectedValueOnce(new Error('git exploded')).mockResolvedValueOnce({ conflict: false, files: [] })
    const { entries } = await run([pr(208, 161), pr(210, 159)], check)
    expect(entries.map((e) => e.state)).toEqual(['error', 'clean'])
  })

  it('a failing PR list is not a crash, but it is said out loud: logged and recorded against the merged PR', async () => {
    const exec = vi.fn(async () => { throw new Error('gh down') })
    const writeStatus = vi.fn()
    const log = vi.fn()
    const entries = await checkOpenPrs({ repo: REPO, mergedPrUrl: MERGED, exec, check: vi.fn(), recordStageFn: vi.fn(), writeStatus, log, now: NOW })
    expect(entries).toEqual([expect.objectContaining({ url: MERGED, pr: 229, state: 'error' })])
    expect(entries[0].reason).toMatch(/could not list the open PRs.*gh down/)
    expect(writeStatus).toHaveBeenCalledWith(entries)
    expect(log).toHaveBeenCalledWith(expect.stringMatching(/post-merge.*gh down/))
  })

  it('an exec that returns no output (the bug that kept this from ever running) is reported, not swallowed', async () => {
    const exec = vi.fn(async () => undefined)
    const log = vi.fn()
    const entries = await checkOpenPrs({ repo: REPO, mergedPrUrl: MERGED, exec, check: vi.fn(), recordStageFn: vi.fn(), writeStatus: vi.fn(), log, now: NOW })
    expect(entries[0].state).toBe('error')
    expect(log).toHaveBeenCalled()
  })

  it('a PR with no linked ticket is still rebased, with no stage-log entry', async () => {
    const { entries, recordStageFn } = await run([pr(208, 161, { body: 'no ticket here' })], vi.fn(async () => ({ ok: true })))
    expect(entries[0].state).toBe('clean')
    expect(recordStageFn).not.toHaveBeenCalled()
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

  it('a PR stacked on the merged one is moved onto main and then checked, so its work cannot miss main', async () => {
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
    const check = vi.fn(async () => ({ conflict: false, files: [] }))
    const entries = await checkOpenPrs({ repo: REPO, mergedPrUrl: MERGED, exec, check, recordStageFn: vi.fn(), writeStatus: vi.fn(), now: NOW })
    expect(calls).toContain(`pr edit https://github.com/${REPO}/pull/230 --base main`)
    expect(calls.some((c) => c.includes('pull/231 --base'))).toBe(false)  // stacked on something else: left alone
    expect(check).toHaveBeenCalledWith('ticket/216-x')
    expect(entries).toEqual([expect.objectContaining({ pr: 230, state: 'clean', retargetedFrom: 'ticket/215-parent' })])
  })

  it('a retarget GitHub refuses leaves the PR stacked and says so', async () => {
    const exec = vi.fn(async (cmd, args) => {
      if (args[1] === 'view') return { stdout: JSON.stringify({ headRefName: 'ticket/215-parent' }), stderr: '' }
      if (args[1] === 'list') return { stdout: JSON.stringify([pr(230, 216, { baseRefName: 'ticket/215-parent' })]), stderr: '' }
      throw new Error('HTTP 422')
    })
    const check = vi.fn(async () => ({ conflict: false, files: [] }))
    const entries = await checkOpenPrs({ repo: REPO, mergedPrUrl: MERGED, exec, check, recordStageFn: vi.fn(), writeStatus: vi.fn(), now: NOW })
    expect(check).not.toHaveBeenCalled()
    expect(entries).toEqual([expect.objectContaining({ pr: 230, state: 'error', reason: expect.stringContaining('couldn\'t move it onto main') })])
  })
})
