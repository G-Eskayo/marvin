import { describe, it, expect, vi } from 'vitest'
import { mainStateFrom, healthCountsFor } from '../webhook-server/merge_order.js'
import { createQueueLoader } from '../webhook-server/merge_facts.js'
import { engineRepo } from '../electron/main/instance.js'

// 2026-11-02: every queued PR waited on "main is red" because the Mini's local health check from 10-31 (commit
// 4af4de63) still said red, while GitHub's CI on main's current commit was green. A local check counts only for the
// commit main is on now.
const OLD = { sha: '4af4de63', ok: false, failed: ['lib/tests/test_playbooks.py::x'] }
const HEAD = '83fd1b46aaaabbbbccccddddeeeeffff00001111'

describe('a local health check counts only for main\'s current commit', () => {
  it('an old red check does not make main red', () => {
    expect(mainStateFrom({ health: OLD, headSha: HEAD }).red).toBe(false)
  })
  it('a red check on the current commit does', () => {
    expect(mainStateFrom({ health: { ...OLD, sha: '83fd1b46' }, headSha: HEAD }).red).toBe(true)
    expect(mainStateFrom({ health: { ...OLD, sha: HEAD }, headSha: HEAD.slice(0, 8) }).red).toBe(true)
  })
  it('unknown head, missing sha, or a too-short sha: the local check is ignored', () => {
    expect(mainStateFrom({ health: OLD }).red).toBe(false)
    expect(healthCountsFor({ ok: false }, HEAD)).toBe(false)
    expect(healthCountsFor({ ok: false, sha: '83f' }, HEAD)).toBe(false)
    expect(healthCountsFor(null, HEAD)).toBe(false)
  })
  it('CI\'s main-red ticket still makes main red, whatever the local check says', () => {
    const issues = [{ number: 992, title: 'Main is red at abc: fix forward', labels: ['bug', 'main-red', 'priority:p0'] }]
    expect(mainStateFrom({ issues, health: { ok: true, sha: HEAD }, headSha: HEAD }).red).toBe(true)
  })
})

describe('the queue loader reads main\'s current commit from GitHub', () => {
  const repo = engineRepo()
  const exec = (head) => vi.fn(async (cmd, args) => {
    if (args[0] === 'api') { if (head instanceof Error) throw head; return { stdout: head + '\n' } }
    return { stdout: '[]' }
  })
  const make = (e) => createQueueLoader({ exec: e, unbuilt: () => new Set(), baseOf: async () => 'main', health: () => OLD, repairs: () => ({}), rebase: () => ({}) })
  it('an old local check on another commit leaves main green', async () => {
    expect((await make(exec(HEAD))(repo)).mainState.red).toBe(false)
  })
  it('the local check on the current commit counts', async () => {
    expect((await make(exec('4af4de63ffff'))(repo)).mainState.red).toBe(true)
  })
  it('GitHub not answering for the head: the local check is ignored, never a guess of red', async () => {
    expect((await make(exec(new Error('rate limited')))(repo)).mainState.red).toBe(false)
  })
})
