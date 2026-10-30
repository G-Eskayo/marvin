import { describe, it, expect, vi } from 'vitest'

// Never write the real logs from a test (same mocks as merge.test.js).
vi.mock('../webhook-server/ticket_stages.js', () => ({ recordStage: vi.fn() }))
vi.mock('../webhook-server/failure_log.js', () => ({ recordFailure: vi.fn(), recordFlaky: vi.fn(), flakySeenBefore: vi.fn(() => false) }))
vi.mock('../webhook-server/rebase_status.js', () => ({ writeRebaseStatus: vi.fn(), readRebaseStatus: vi.fn(() => ({})) }))
vi.mock('../webhook-server/ui_evidence.js', () => ({ assertUiEvidence: vi.fn(async () => {}) }))
vi.mock('../webhook-server/decisions_gate.js', () => ({ assertDecisions: vi.fn(async () => {}) }))
vi.mock('../webhook-server/changelog.js', () => ({ applyVersionBump: vi.fn().mockResolvedValue(undefined) }))

import { execFile, execFileSync } from 'child_process'
import { promisify } from 'util'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { rebaseAndRetest, rerunFailingTests, mergePr, FLAKY_RERUN_MAX } from '../webhook-server/merge.js'
import { recordStage } from '../webhook-server/ticket_stages.js'
import { recordFailure, recordFlaky, flakySeenBefore } from '../webhook-server/failure_log.js'

// Failure containment (2026-10-30): PR #892 was sent back because test/fits_window.test.jsx, a test it never touched,
// failed once in the gate. A test the PR didn't change that fails, then passes when run again, is flaky: it is named and
// the owner is told, and the PR is not sent back for it.

const realExec = promisify(execFile)
const sh = (cmd, args, cwd) => execFileSync(cmd, args, { cwd, stdio: 'pipe' }).toString()
const PLENTY = async () => 100 * 1024 ** 3

// A real origin and clone with a PR branch `feature` that changes `files` (path -> text).
function fixture(files = { 'f.txt': 'x\n' }) {
  const root = mkdtempSync(path.join(tmpdir(), 'gate-flaky-'))
  const origin = path.join(root, 'origin.git')
  const repo = path.join(root, 'repo')
  sh('git', ['init', '-q', '--bare', '-b', 'main', origin])
  sh('git', ['clone', '-q', origin, repo])
  sh('git', ['config', 'user.email', 't@t'], repo); sh('git', ['config', 'user.name', 't'], repo)
  writeFileSync(path.join(repo, 'README.md'), 'hi\n'); sh('git', ['add', '.'], repo); sh('git', ['commit', '-qm', 'init'], repo)
  sh('git', ['push', '-q', '-u', 'origin', 'main'], repo)
  sh('git', ['checkout', '-qb', 'feature'], repo)
  for (const [p, text] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(repo, p)), { recursive: true })
    writeFileSync(path.join(repo, p), text)
  }
  sh('git', ['add', '.'], repo); sh('git', ['commit', '-qm', 'feature'], repo)
  sh('git', ['push', '-q', '-u', 'origin', 'feature'], repo)
  return { root, repo }
}

const vitestFail = (...names) => Object.assign(new Error('Command failed: npx vitest run'), {
  stdout: `${names.map((n) => ` FAIL  ${n}`).join('\n')}\n Test Files  ${names.length} failed | 170 passed (171)\n`, stderr: ''
})
const pytestFail = (...ids) => Object.assign(new Error('Command failed: python -m pytest -q'), {
  stdout: `${ids.map((n) => `FAILED ${n} - AssertionError`).join('\n')}\n${ids.length} failed, 4000 passed\n`, stderr: ''
})
const failingWith = (err) => async () => { throw err }

describe('rebaseAndRetest: one rerun of a failing test the PR did not touch', () => {
  const run = (repo, runTests, rerun) =>
    rebaseAndRetest('feature', realExec, repo, runTests, 'main', null, null, undefined, PLENTY, null, rerun)

  it('passes on the rerun: the gate passes, names the flaky test, and still pushes the rebased branch', async () => {
    const { root, repo } = fixture()
    try {
      const rerun = vi.fn(async () => true)
      const r = await run(repo, failingWith(vitestFail('test/fits_window.test.jsx > fits > keeps the window')), rerun)
      expect(r).toEqual({ ok: true, flaky: ['test/fits_window.test.jsx > fits > keeps the window'] })
      expect(rerun).toHaveBeenCalledTimes(1)
      expect(rerun.mock.calls[0][1]).toEqual(['test/fits_window.test.jsx > fits > keeps the window'])
    } finally { rmSync(root, { recursive: true, force: true }) }
  })

  it('fails again on the rerun: a real failure, reported exactly as before', async () => {
    const { root, repo } = fixture()
    try {
      const r = await run(repo, failingWith(pytestFail('lib/tests/test_x.py::test_y')), vi.fn(async () => false))
      expect(r.ok).toBe(false)
      expect(r.reason).toContain('FAILED lib/tests/test_x.py::test_y')
      expect(r.flaky).toBeUndefined()
    } finally { rmSync(root, { recursive: true, force: true }) }
  })

  it('never reruns a test the PR itself changed (its own flakiness is its own fault)', async () => {
    const { root, repo } = fixture({ 'dashboard/test/fits_window.test.jsx': 'changed\n' })
    try {
      const rerun = vi.fn(async () => true)
      const r = await run(repo, failingWith(vitestFail('test/fits_window.test.jsx > fits > keeps the window')), rerun)
      expect(r.ok).toBe(false)
      expect(rerun).not.toHaveBeenCalled()
    } finally { rmSync(root, { recursive: true, force: true }) }
  })

  it('never reruns a pytest file the PR changed', async () => {
    const { root, repo } = fixture({ 'lib/tests/test_x.py': 'changed\n' })
    try {
      const rerun = vi.fn(async () => true)
      expect((await run(repo, failingWith(pytestFail('lib/tests/test_x.py::test_y')), rerun)).ok).toBe(false)
      expect(rerun).not.toHaveBeenCalled()
    } finally { rmSync(root, { recursive: true, force: true }) }
  })

  it(`more than ${FLAKY_RERUN_MAX} failing tests is a real break, not a flake: no rerun`, async () => {
    const { root, repo } = fixture()
    try {
      const ids = Array.from({ length: FLAKY_RERUN_MAX + 1 }, (_, i) => `lib/tests/test_${i}.py::test_a`)
      const rerun = vi.fn(async () => true)
      expect((await run(repo, failingWith(pytestFail(...ids)), rerun)).ok).toBe(false)
      expect(rerun).not.toHaveBeenCalled()
    } finally { rmSync(root, { recursive: true, force: true }) }
  })

  it('a failure with no test names (a crash, a collection error wall) is not rerun', async () => {
    const { root, repo } = fixture()
    try {
      const rerun = vi.fn(async () => true)
      const crash = Object.assign(new Error('Command failed: npx vitest run'), { stdout: 'Segmentation fault\n', stderr: '' })
      expect((await run(repo, failingWith(crash), rerun)).ok).toBe(false)
      expect(rerun).not.toHaveBeenCalled()
    } finally { rmSync(root, { recursive: true, force: true }) }
  })

  it('a rerun that throws counts as a failure, never a pass', async () => {
    const { root, repo } = fixture()
    try {
      const r = await run(repo, failingWith(pytestFail('lib/tests/test_x.py::test_y')), vi.fn(async () => { throw new Error('boom') }))
      expect(r.ok).toBe(false)
    } finally { rmSync(root, { recursive: true, force: true }) }
  })

  it('a rerun that answers anything but true counts as a failure', async () => {
    const { root, repo } = fixture()
    try {
      for (const answer of [undefined, null, 'yes', 1, {}]) {
        const r = await run(repo, failingWith(pytestFail('lib/tests/test_x.py::test_y')), vi.fn(async () => answer))
        expect(r.ok).toBe(false)
      }
    } finally { rmSync(root, { recursive: true, force: true }) }
  }, 60_000)

  it('without a rerunner (other projects), behaves exactly as before', async () => {
    const { root, repo } = fixture()
    try {
      const r = await rebaseAndRetest('feature', realExec, repo, failingWith(vitestFail('test/a.test.js')), 'main', null, null, undefined, PLENTY)
      expect(r.ok).toBe(false)
    } finally { rmSync(root, { recursive: true, force: true }) }
  })
})

describe('rerunFailingTests: what one rerun runs', () => {
  const recorder = (fail = () => false) => {
    const calls = []
    const exec = vi.fn(async (cmd, args, opts) => {
      calls.push({ cmd, args, cwd: opts?.cwd })
      if (fail(cmd, args)) throw Object.assign(new Error('Command failed'), { stdout: 'FAILED', stderr: '' })
      return { stdout: '', stderr: '' }
    })
    return { exec, calls }
  }

  it('a dashboard test: reruns just that file with vitest in dashboard/', async () => {
    const { exec, calls } = recorder()
    expect(await rerunFailingTests('/scratch', ['test/fits_window.test.jsx > fits > keeps the window'], exec)).toBe(true)
    expect(calls).toEqual([{ cmd: 'npx', args: ['vitest', 'run', 'test/fits_window.test.jsx'], cwd: '/scratch/dashboard' }])
  })

  it('a Python test: reruns that id, then the whole dashboard suite, which never ran after pytest failed', async () => {
    const { exec, calls } = recorder()
    expect(await rerunFailingTests('/scratch', ['lib/tests/test_x.py::test_y'], exec)).toBe(true)
    expect(calls[0].cmd).toMatch(/python/)
    expect(calls[0].args).toEqual(expect.arrayContaining(['-m', 'pytest', 'lib/tests/test_x.py::test_y']))
    expect(calls[0].cwd).toBe('/scratch')
    expect(calls[1]).toEqual({ cmd: 'npx', args: ['vitest', 'run'], cwd: '/scratch/dashboard' })
  })

  it('still failing: false', async () => {
    const { exec } = recorder(() => true)
    expect(await rerunFailingTests('/scratch', ['test/a.test.js'], exec)).toBe(false)
  })

  it('the Python rerun passes but the dashboard suite fails: false', async () => {
    const { exec } = recorder((cmd) => cmd === 'npx')
    expect(await rerunFailingTests('/scratch', ['lib/tests/test_x.py::test_y'], exec)).toBe(false)
  })

  it('a name it cannot map to a test file runs nothing and is false', async () => {
    for (const odd of ['SomeSuite/testName', '', 'rm -rf /', '--version', '../../etc/passwd::x', 'test/../../x.test.js']) {
      const { exec, calls } = recorder()
      expect(await rerunFailingTests('/scratch', [odd], exec)).toBe(false)
      expect(calls).toEqual([])
    }
  })

  it('no names: false, nothing run', async () => {
    const { exec, calls } = recorder()
    expect(await rerunFailingTests('/scratch', [], exec)).toBe(false)
    expect(calls).toEqual([])
  })
})

describe('mergePr: a flaky pass holds for Approve again (Gil 2026-10-30), then merges', () => {
  const PR = 'https://github.com/G-Eskayo/marvin/pull/892'
  const gate = () => vi.fn().mockResolvedValue({ gate: true, headRefName: 'pipeline/x', body: 'Closes G-Eskayo/marvin#891' })
  const noop = vi.fn()
  const world = (commentFails = false) => {
    const calls = []
    const exec = vi.fn(async (cmd, args) => {
      calls.push([cmd, ...args])
      if (commentFails && cmd === 'gh' && args[0] === 'pr' && args[1] === 'comment') throw new Error('GitHub down')
      return { stdout: JSON.stringify({ baseRefName: 'main', statusCheckRollup: [] }), stderr: '' }
    })
    const rebase = vi.fn().mockResolvedValue({ ok: true, flaky: ['test/fits_window.test.jsx'] })
    const reengage = vi.fn()
    const run = () => mergePr(PR, exec, noop, noop, gate(), rebase, reengage, recordStage, { rebaseOpen: async () => {} })
    const merged = () => calls.some((c) => c[0] === 'gh' && c[1] === 'pr' && c[2] === 'merge')
    return { run, calls, reengage, merged }
  }

  it('first time: holds, never merges, names the test, records it, and neither sends it back nor feeds the breaker', async () => {
    flakySeenBefore.mockReturnValueOnce(false)
    const w = world()
    await expect(w.run()).rejects.toMatchObject({ payload: { code: 'FLAKY_HOLD', stage: 'gate', action: 'escalate' } })
    expect(w.merged()).toBe(false)
    expect(w.reengage).not.toHaveBeenCalled()
    const comment = w.calls.find((c) => c[0] === 'gh' && c[1] === 'pr' && c[2] === 'comment')
    expect(comment.join(' ')).toContain('test/fits_window.test.jsx')
    expect(comment.join(' ')).toContain('Approve it again')
    expect(recordFlaky).toHaveBeenCalledWith(expect.objectContaining({ tests: ['test/fits_window.test.jsx'], prUrl: PR }))
    // A flake is not a failure: it must never feed the cross-ticket breaker, which would pause dispatch.
    expect(recordFailure).not.toHaveBeenCalled()
  })

  it('approved again after the hold, with the same flaky test: merges (no endless hold on a test that keeps flaking)', async () => {
    flakySeenBefore.mockReturnValueOnce(true)
    const w = world()
    const r = await w.run()
    expect(r.merged).toBe(true)
    expect(flakySeenBefore).toHaveBeenLastCalledWith(PR, ['test/fits_window.test.jsx'])
  })

  it('a check of the history that throws counts as not seen: it holds, never merges by accident', async () => {
    flakySeenBefore.mockImplementationOnce(() => { throw new Error('log unreadable') })
    const w = world()
    await expect(w.run()).rejects.toMatchObject({ payload: { code: 'FLAKY_HOLD' } })
    expect(w.merged()).toBe(false)
  })

  it('a comment GitHub refuses never turns the hold into a merge', async () => {
    flakySeenBefore.mockReturnValueOnce(false)
    const w = world(true)
    await expect(w.run()).rejects.toMatchObject({ payload: { code: 'FLAKY_HOLD' } })
    expect(w.merged()).toBe(false)
  })
})
