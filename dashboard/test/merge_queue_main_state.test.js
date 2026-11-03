import { describe, it, expect, vi } from 'vitest'
import { mainStateFrom, healthCountsFor, mergeOrder } from '../webhook-server/merge_order.js'
import { createQueueLoader, createFallbackRun, createDeadlineWake, mainCiFacts } from '../webhook-server/merge_facts.js'
import { mainCiHead } from '../webhook-server/gh_watch.js'
import { engineRepo } from '../electron/main/instance.js'

// marvin#1094 (Gil, 2026-11-03): GitHub's CI is the only judge of whether main is green. 13 main-red fixes in four days
// were tests that failed on the Mini only while CI on main was green; on 2026-11-02 the Mini's check on an older commit
// held every merge. CI's verdict on main's head (lib/main_ci.py) decides; a local run counts only as the fallback when
// CI is silent past its deadline, and only for that very commit.
const HEAD = '83fd1b46aaaabbbbccccddddeeeeffff00001111'
const OLDER = '4af4de63aaaabbbbccccddddeeeeffff00002222'
const ci = (state, extra = {}) => ({ sha: HEAD, state, failing: state === 'red' ? ['Python tests'] : [], pending: state === 'pending' ? ['Python tests'] : [],
  reason: { pending: `CI is still checking main @ ${HEAD.slice(0, 7)} (Python tests)`, late: `CI hasn't reported on main @ ${HEAD.slice(0, 7)} in 50 min, so main is being checked on this Mac once instead`, red: 'GitHub\'s CI failed on main', green: 'GitHub\'s CI passed on main', unknown: 'GitHub\'s CI result for main could not be read' }[state],
  deadline_at: '2026-11-03T20:31:00+00:00', runs: [{ name: 'Python tests', status: state === 'pending' ? 'in_progress' : 'completed', conclusion: null }], ...extra })
const localRed = { sha: HEAD.slice(0, 8), ok: false, failed: ['lib/tests/test_scanner_handover.py::x'] }
const localGreen = { sha: HEAD.slice(0, 8), ok: true, failed: [] }

const REPO = engineRepo()
const url = (n) => `https://github.com/${REPO}/pull/${n}`
const pr = (n, extra = {}) => ({ url: url(n), number: n, repo: REPO, baseRefName: 'main', headRefName: `b${n}`, body: 'Closes #1', mergeable: 'MERGEABLE', statusCheckRollup: [], ...extra })
const q = (...ns) => ({ items: ns.map((n, i) => ({ url: url(n), approvedAt: i + 1 })), failed: {}, lastMerged: null, running: null })

describe('CI\'s verdict on main\'s head is the judge', () => {
  it('CI red on the head blocks the queue, even with a green local run on the same commit', () => {
    const main = mainStateFrom({ ci: ci('red'), health: localGreen })
    expect(main).toMatchObject({ red: true, ciRed: true, judge: 'ci' })
    const out = mergeOrder([pr(1)], main, q(1))
    expect(out.next).toBeNull()
    expect(out.entries[url(1)].reason).toBe('main is red · waits for a fix')
  })

  it('CI green with the local run red on the same commit does not block', () => {
    const main = mainStateFrom({ ci: ci('green'), health: localRed })
    expect(main).toMatchObject({ red: false, healthRed: false, waiting: null })
    expect(mergeOrder([pr(1)], main, q(1)).next).toBe(url(1))
  })

  it('CI still checking the head: the queue waits and says so, whatever the local run says', () => {
    for (const health of [null, localGreen, localRed]) {
      const main = mainStateFrom({ ci: ci('pending'), health })
      expect(main.red).toBe(false)
      const out = mergeOrder([pr(1)], main, q(1))
      expect(out.next).toBeNull()
      expect(out.entries[url(1)]).toMatchObject({ state: 'waiting', tone: 'amber' })
      expect(out.entries[url(1)].reason).toContain('CI is still checking main')
    }
  })

  it('GitHub unreadable: unknown waits, never a guess of green', () => {
    const out = mergeOrder([pr(1)], mainStateFrom({ ci: ci('unknown'), health: localGreen }), q(1))
    expect(out.next).toBeNull()
    expect(out.entries[url(1)].reason).toContain('could not be read')
  })

  it('CI silent past the deadline with no local run on the head: wait, ask for the one local run, and say why', () => {
    const main = mainStateFrom({ ci: ci('late'), health: { ...localRed, sha: OLDER.slice(0, 8) } })
    expect(main).toMatchObject({ red: false, fallback: true })
    const out = mergeOrder([pr(1)], main, q(1))
    expect(out.next).toBeNull()
    expect(out.entries[url(1)].reason).toContain('on this Mac once')
  })

  it('CI silent past the deadline: the local run on the head is the fallback judge, red or green, and the reason says so', () => {
    const red = mainStateFrom({ ci: ci('late'), health: localRed })
    expect(red).toMatchObject({ red: true, healthRed: true, judge: 'local fallback', fallback: false })
    expect(mergeOrder([pr(1)], red, q(1)).entries[url(1)].reason).toBe('main is red on this Mac (CI silent) · waits for a fix')
    const green = mainStateFrom({ ci: ci('late'), health: localGreen })
    expect(green).toMatchObject({ red: false, judge: 'local fallback', waiting: null })
    expect(mergeOrder([pr(1)], green, q(1)).next).toBe(url(1))
  })

  it('a stale CI result, for an older commit than main\'s head, does not count: the queue waits for the head\'s', () => {
    const main = mainStateFrom({ ci: ci('green', { sha: OLDER }), headSha: HEAD })
    expect(main.red).toBe(false)
    expect(main.waiting).toContain('CI is still checking main')
    expect(mergeOrder([pr(1)], main, q(1)).next).toBeNull()
    expect(mainStateFrom({ ci: ci('red', { sha: OLDER }), headSha: HEAD }).red).toBe(false)
  })

  it('an old local run never counts, even in the fallback', () => {
    expect(mainStateFrom({ ci: ci('late'), health: { ...localRed, sha: OLDER } }).red).toBe(false)
    expect(healthCountsFor({ ok: false, sha: '83f' }, HEAD)).toBe(false)
    expect(healthCountsFor({ ok: false }, HEAD)).toBe(false)
    expect(healthCountsFor(null, HEAD)).toBe(false)
  })

  it('a fix for a red main may still go while CI checks, and CI\'s main-red ticket is red whatever CI says now', () => {
    const issues = [{ number: 992, title: 'Main is red at abc: fix forward', labels: ['bug', 'main-red', 'priority:p0'] }]
    const main = mainStateFrom({ issues, ci: ci('pending') })
    expect(main.red).toBe(true)
    const out = mergeOrder([pr(1, { body: 'Closes #992' }), pr(2)], main, q(2, 1))
    expect(out.next).toBe(url(1))
    expect(mainStateFrom({ issues, ci: ci('green') }).red).toBe(true)
  })

  it('without a CI verdict (another project) only the tickets judge, and a local run is ignored', () => {
    expect(mainStateFrom({ health: localRed, headSha: HEAD })).toMatchObject({ red: false, waiting: null, judge: 'tickets' })
  })
})

describe('the queue loader asks lib/main_ci.py for CI\'s verdict', () => {
  const repo = engineRepo()
  const exec = (verdict) => vi.fn(async (cmd, args) => {
    if (String(args[0]).endsWith('main_ci.py')) { if (verdict instanceof Error) throw verdict; return { stdout: JSON.stringify(verdict) } }
    return { stdout: '[]' }
  })
  const make = (e, extra = {}) => createQueueLoader({ exec: e, unbuilt: () => new Set(), baseOf: async () => 'main', health: () => localRed, repairs: () => ({}), rebase: () => ({}), ...extra })

  it('CI green: main green, the local red ignored', async () => {
    expect((await make(exec(ci('green')))(repo)).mainState).toMatchObject({ red: false, waiting: null })
  })
  it('CI red: main red', async () => {
    expect((await make(exec(ci('red')))(repo)).mainState.red).toBe(true)
  })
  it('the verdict script failing is unknown: the queue waits', async () => {
    const { mainState } = await make(exec(new Error('python died')))(repo)
    expect(mainState.red).toBe(false)
    expect(mainState.waiting).toContain('could not be read')
  })
  it('pending asks to decide again at CI\'s deadline; late with no local run on the head asks for the fallback once', async () => {
    const wakeAt = vi.fn()
    const fallback = vi.fn()
    await make(exec(ci('pending')), { wakeAt, fallback })(repo)
    expect(wakeAt).toHaveBeenCalledWith(repo, Date.parse('2026-11-03T20:31:00+00:00'))
    expect(fallback).not.toHaveBeenCalled()
    await make(exec(ci('late')), { wakeAt, fallback, health: () => ({ ...localRed, sha: OLDER }) })(repo)
    expect(fallback).toHaveBeenCalledWith(repo, HEAD)
  })
  it('late with a local run on the head already: no new run', async () => {
    const fallback = vi.fn()
    const { mainState } = await make(exec(ci('late')), { fallback })(repo)
    expect(mainState.red).toBe(true)
    expect(fallback).not.toHaveBeenCalled()
  })
  it('another repo never asks CI\'s verdict script (marvin\'s own CI files the main-red ticket)', async () => {
    const e = exec(ci('red'))
    expect((await make(e)('someone/other')).mainState.red).toBe(false)
    expect(e.mock.calls.some(([, args]) => String(args[0]).endsWith('main_ci.py'))).toBe(false)
  })
})

describe('the fallback runs once per commit, and its end is the next trigger', () => {
  const child = () => { const on = {}; return { on: (ev, f) => { on[ev] = f }, fire: (ev) => on[ev]?.() } }
  it('one run per sha, main_health.py refresh, and done(repo) when it exits', () => {
    const kids = []
    const spawn = vi.fn(() => { const c = child(); kids.push(c); return c })
    const done = vi.fn()
    const run = createFallbackRun({ spawn, python: 'py', script: 'main_health.py', done })
    expect(run(REPO, HEAD)).toBe(true)
    expect(run(REPO, HEAD)).toBe(false)
    expect(spawn).toHaveBeenCalledTimes(1)
    expect(spawn.mock.calls[0].slice(0, 2)).toEqual(['py', ['main_health.py', 'refresh']])
    kids[0].fire('exit')
    expect(done).toHaveBeenCalledWith(REPO)
    expect(run(REPO, OLDER)).toBe(true)
  })
  it('a spawn that throws still triggers, so the queue is never left waiting on nothing', () => {
    const done = vi.fn()
    createFallbackRun({ spawn: () => { throw new Error('ENOENT') }, done })(REPO, HEAD)
    expect(done).toHaveBeenCalledWith(REPO)
  })
})

describe('the deadline wake is one timer per repo, at a known time', () => {
  it('sets one timer, replaces it for a new deadline, and kicks the repo when it fires', () => {
    const timers = []
    const setTimer = vi.fn((f, ms) => { const t = { f, ms }; timers.push(t); return t })
    const clearTimer = vi.fn()
    const kick = vi.fn()
    const wake = createDeadlineWake({ kick, setTimer, clearTimer, now: () => 1_000 })
    wake(REPO, 61_000)
    wake(REPO, 61_000)
    expect(setTimer).toHaveBeenCalledTimes(1)
    expect(timers[0].ms).toBe(61_000)
    wake(REPO, 121_000)
    expect(clearTimer).toHaveBeenCalledWith(timers[0])
    timers[1].f()
    expect(kick).toHaveBeenCalledWith(REPO)
  })
})

describe('main\'s head is watched while the queue waits for CI', () => {
  it('pending: watched with a digest of its checks; any other state: not watched', () => {
    const head = mainCiHead(REPO, mainStateFrom({ ci: ci('pending') }))
    expect(head).toEqual({ repo: REPO, sha: HEAD, checkRuns: 'Python tests|running', statuses: null })
    for (const s of ['green', 'red', 'late']) expect(mainCiHead(REPO, mainStateFrom({ ci: ci(s) }))).toBeNull()
    expect(mainCiHead(REPO, null)).toBeNull()
  })
  it('MR Review gets the same verdict the queue decided on', () => {
    const queue = { snapshot: () => ({ [REPO]: {} }), view: () => ({ main: mainStateFrom({ ci: ci('red') }) }) }
    expect(mainCiFacts(queue)[REPO]).toMatchObject({ sha: HEAD, state: 'red' })
  })
})
