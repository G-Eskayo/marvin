import { describe, it, expect, vi } from 'vitest'

// mergePr()'s new stage-recording calls write real files under
// ~/.claude/logs/ticket-stages/<n>.json by default -- found live
// 2026-10-01: these tests' fixture PR bodies reference real-looking
// ticket numbers (e.g. #5), and ran unmocked they wrote real files.
// Mocked at the module level (not per-call-site) since mergePr is called
// with positional args throughout this file and recordStageFn is the
// last of eight.
vi.mock('../webhook-server/ticket_stages.js', () => ({ recordStage: vi.fn() }))
// Likewise the approve-failure log (shared with lib/failure_breaker.py): never write the
// real ~/.claude/logs/pipeline-failures.jsonl from a test.
vi.mock('../webhook-server/failure_log.js', () => ({ recordFailure: vi.fn() }))

import { execFile, execFileSync } from 'child_process'
import { promisify } from 'util'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import {
  mergePr,
  triggerRebuildIfDashboardChanged,
  triggerTicketPipeline,
  isBehindMain,
  rebaseAndRetest,
  _defaultRunTests
} from '../webhook-server/merge.js'

const realExec = promisify(execFile)

// mergePr's rebuild/redispatch defaults are the real fire-and-forget
// triggers -- every test that reaches past the URL check must override
// both, or it'll spawn a real subprocess (a real npm build, a real
// ticket_pipeline.py run) during the test suite.
function noopRebuild() {
  return Promise.resolve()
}
function noopRedispatch() {}

describe('mergePr', () => {
  it('rejects a non-GitHub URL without calling exec', async () => {
    const exec = vi.fn()
    await expect(mergePr('not-a-url', exec)).rejects.toThrow('Not a GitHub PR URL')
    expect(exec).not.toHaveBeenCalled()
  })

  it('rejects a non-string input without throwing a different error', async () => {
    const exec = vi.fn()
    await expect(mergePr(undefined, exec)).rejects.toThrow('Not a GitHub PR URL')
    expect(exec).not.toHaveBeenCalled()
  })

  it('calls gh pr merge with the exact URL for a valid GitHub PR link', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    await mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec, noopRebuild, noopRedispatch)
    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'merge', 'https://github.com/G-Eskayo/marvin/pull/71', '--merge'])
  })

  it('propagates a failure from the underlying gh call', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('merge conflict'))
    await expect(mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec)).rejects.toThrow('merge conflict')
  })

  it('checks for a dashboard rebuild after a successful merge', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const rebuild = vi.fn().mockResolvedValue(undefined)
    await mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec, rebuild, noopRedispatch)
    expect(rebuild).toHaveBeenCalledWith('https://github.com/G-Eskayo/marvin/pull/71', exec)
  })

  it('triggers a ticket-pipeline redispatch after a successful merge, regardless of what was touched', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const redispatch = vi.fn()
    await mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec, noopRebuild, redispatch)
    expect(redispatch).toHaveBeenCalledTimes(1)
  })

  it('does not trigger a redispatch when the merge itself fails', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('merge conflict'))
    const redispatch = vi.fn()
    await expect(mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec, noopRebuild, redispatch)).rejects.toThrow()
    expect(redispatch).not.toHaveBeenCalled()
  })

  // G-Eskayo/marvin#91 -- ADR 0026's merge-time gate.
  it('skips the gate and merges directly when the branch is already up to date', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const shouldGateMerge = vi.fn().mockResolvedValue({ gate: false, headRefName: 'some-branch', body: '' })
    const rebaseAndRetestFn = vi.fn()

    const result = await mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec, noopRebuild, noopRedispatch, shouldGateMerge, rebaseAndRetestFn)

    expect(rebaseAndRetestFn).not.toHaveBeenCalled()
    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'merge', 'https://github.com/G-Eskayo/marvin/pull/71', '--merge'])
    expect(result).toEqual({ merged: true, reengaged: false, reason: null })
  })

  it('rebases and still merges when behind main but the retest passes', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const shouldGateMerge = vi.fn().mockResolvedValue({ gate: true, headRefName: 'pipeline/g-eskayo/marvin#5', body: 'Closes G-Eskayo/marvin#5' })
    const rebaseAndRetestFn = vi.fn().mockResolvedValue({ ok: true })
    const reengage = vi.fn()

    const result = await mergePr(
      'https://github.com/G-Eskayo/marvin/pull/71', exec, noopRebuild, noopRedispatch, shouldGateMerge, rebaseAndRetestFn, reengage
    )

    expect(rebaseAndRetestFn).toHaveBeenCalledWith('pipeline/g-eskayo/marvin#5', exec)
    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'merge', 'https://github.com/G-Eskayo/marvin/pull/71', '--merge'])
    expect(reengage).not.toHaveBeenCalled()
    expect(result).toEqual({ merged: true, reengaged: false, reason: null })
  })

  it('records a stage timeline for a clean gated merge: gate started/passed, merging, rebuilding, done', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const shouldGateMerge = vi.fn().mockResolvedValue({ gate: true, headRefName: 'pipeline/g-eskayo/marvin#5', body: 'Closes G-Eskayo/marvin#5' })
    const rebaseAndRetestFn = vi.fn().mockResolvedValue({ ok: true })
    const recordStageFn = vi.fn()

    await mergePr(
      'https://github.com/G-Eskayo/marvin/pull/71', exec, noopRebuild, noopRedispatch,
      shouldGateMerge, rebaseAndRetestFn, vi.fn(), recordStageFn
    )

    const stages = recordStageFn.mock.calls.map(([, stage, status]) => `${stage}:${status}`)
    expect(stages).toEqual(['gate:started', 'gate:passed', 'merging:started', 'merging:passed', 'rebuilding:started', 'done:passed'])
    expect(recordStageFn.mock.calls.every(([ticketNumber]) => ticketNumber === '5')).toBe(true)
  })

  it('records gate:failed and nothing after, when the rebase/retest fails (no false merging/done events)', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const shouldGateMerge = vi.fn().mockResolvedValue({ gate: true, headRefName: 'pipeline/g-eskayo/marvin#5', body: 'Closes G-Eskayo/marvin#5' })
    const rebaseAndRetestFn = vi.fn().mockResolvedValue({ ok: false, reason: 'boom' })
    const recordStageFn = vi.fn()

    await mergePr(
      'https://github.com/G-Eskayo/marvin/pull/71', exec, noopRebuild, noopRedispatch,
      shouldGateMerge, rebaseAndRetestFn, vi.fn().mockResolvedValue(undefined), recordStageFn
    )

    const stages = recordStageFn.mock.calls.map(([, stage, status]) => `${stage}:${status}`)
    expect(stages).toEqual(['gate:started', 'gate:failed'])
  })

  it('records no stage events at all when the PR has no linked ticket', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const shouldGateMerge = vi.fn().mockResolvedValue({ gate: false, headRefName: 'some-branch', body: '' })
    const recordStageFn = vi.fn()

    await mergePr(
      'https://github.com/G-Eskayo/marvin/pull/71', exec, noopRebuild, noopRedispatch,
      shouldGateMerge, vi.fn(), vi.fn(), recordStageFn
    )

    expect(recordStageFn).not.toHaveBeenCalled()
  })

  it('routes to re-engagement and does not merge when the rebase or retest fails', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const shouldGateMerge = vi.fn().mockResolvedValue({ gate: true, headRefName: 'pipeline/g-eskayo/marvin#5', body: 'Closes G-Eskayo/marvin#5' })
    const rebaseAndRetestFn = vi.fn().mockResolvedValue({ ok: false, reason: 'Tests failed after rebasing onto main:\n\nboom' })
    const reengage = vi.fn().mockResolvedValue(undefined)
    const rebuild = vi.fn()
    const redispatch = vi.fn()

    const result = await mergePr(
      'https://github.com/G-Eskayo/marvin/pull/71', exec, rebuild, redispatch, shouldGateMerge, rebaseAndRetestFn, reengage
    )

    // Contract changed 2026-10-02: the feedback sent back to the ticket is now a structured,
    // parseable comment (code header, failing test names, capped tail), not the raw wall.
    expect(reengage).toHaveBeenCalledWith(
      expect.objectContaining({
        prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
        ticketNumber: '5',
        reasons: ['Regression/quality'],
        comment: expect.stringContaining('**Merge gate: GATE_TESTS_FAILED**')
      }),
      exec
    )
    expect(exec).not.toHaveBeenCalledWith('gh', ['pr', 'merge', 'https://github.com/G-Eskayo/marvin/pull/71', '--merge'])
    expect(rebuild).not.toHaveBeenCalled()
    expect(redispatch).not.toHaveBeenCalled()
    expect(result).toMatchObject({ merged: false, reengaged: true, code: 'GATE_TESTS_FAILED', stage: 'gate', action: 'reengage' })
    expect(result.reason).toContain('boom')
  })
})

describe('triggerRebuildIfDashboardChanged', () => {
  it('does nothing when the PR touched no dashboard files', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: 'skills/paper-dive/foo.py\nCONTEXT.md\n', stderr: '' })
    // Should resolve cleanly without attempting to spawn a real script.
    await expect(triggerRebuildIfDashboardChanged('https://github.com/G-Eskayo/marvin/pull/1', exec)).resolves.toBeUndefined()
  })

  it('does not throw when the gh pr view call fails', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('not found'))
    await expect(triggerRebuildIfDashboardChanged('https://github.com/G-Eskayo/marvin/pull/1', exec)).resolves.toBeUndefined()
  })

  it('queries gh pr view for the files touched by the PR', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: 'CONTEXT.md\n', stderr: '' })
    await triggerRebuildIfDashboardChanged('https://github.com/G-Eskayo/marvin/pull/1', exec)
    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'view', 'https://github.com/G-Eskayo/marvin/pull/1', '--json', 'files', '--jq', '.files[].path'])
  })

  it('spawns the rebuild script, detached, when a dashboard file was touched', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: 'dashboard/src/App.jsx\n', stderr: '' })
    const unref = vi.fn()
    const spawnFn = vi.fn().mockReturnValue({ unref })
    await triggerRebuildIfDashboardChanged('https://github.com/G-Eskayo/marvin/pull/1', exec, spawnFn)
    expect(spawnFn).toHaveBeenCalledTimes(1)
    const [scriptPath, args, opts] = spawnFn.mock.calls[0]
    expect(scriptPath).toMatch(/scripts\/rebuild_and_install\.sh$/)
    expect(args).toEqual([])
    expect(opts).toMatchObject({ detached: true, stdio: 'ignore' })
    expect(unref).toHaveBeenCalled()
  })

  it('does not spawn when no touched file is under dashboard/', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: 'skills/paper-dive/foo.py\n', stderr: '' })
    const spawnFn = vi.fn()
    await triggerRebuildIfDashboardChanged('https://github.com/G-Eskayo/marvin/pull/1', exec, spawnFn)
    expect(spawnFn).not.toHaveBeenCalled()
  })
})

describe('triggerTicketPipeline', () => {
  it('spawns ticket_pipeline.py detached, unconditionally', () => {
    const unref = vi.fn()
    const spawnFn = vi.fn().mockReturnValue({ unref })
    triggerTicketPipeline(spawnFn)
    expect(spawnFn).toHaveBeenCalledTimes(1)
    const [pythonPath, args, opts] = spawnFn.mock.calls[0]
    expect(pythonPath).toMatch(/venv\/bin\/python$/)
    expect(args).toHaveLength(1)
    expect(args[0]).toMatch(/lib\/ticket_pipeline\.py$/)
    expect(opts).toMatchObject({ detached: true, stdio: 'ignore' })
    expect(unref).toHaveBeenCalled()
  })
})

// Real git fixtures (a bare "origin" + a local clone standing in for
// merge.js's REPO_PATH) -- what's under test here is actual git rebase/
// fetch/worktree behavior, not something worth mocking away. Only the
// "run the test suite" step is faked (no real pytest/vitest environment
// inside a throwaway fixture repo).
function sh(cmd, args, cwd) {
  return execFileSync(cmd, args, { cwd, encoding: 'utf-8' })
}

function makeGitFixture() {
  const root = mkdtempSync(path.join(tmpdir(), 'merge-gate-fixture-'))
  const originDir = path.join(root, 'origin.git')
  const repoDir = path.join(root, 'repo')
  sh('git', ['init', '--quiet', '--bare', originDir])
  sh('git', ['clone', '--quiet', originDir, repoDir])
  sh('git', ['config', 'user.email', 'test@test.com'], repoDir)
  sh('git', ['config', 'user.name', 'Test'], repoDir)
  writeFileSync(path.join(repoDir, 'README.md'), 'hello\n')
  sh('git', ['add', '.'], repoDir)
  sh('git', ['commit', '-q', '-m', 'init'], repoDir)
  sh('git', ['branch', '-M', 'main'], repoDir)
  sh('git', ['push', '-u', 'origin', 'main'], repoDir)
  return { root, repoDir }
}

function currentRemoteSha(repoDir, ref) {
  sh('git', ['fetch', 'origin', ref], repoDir)
  return sh('git', ['rev-parse', `origin/${ref}`], repoDir).trim()
}

describe('isBehindMain', () => {
  it('is false when the branch already contains the latest main', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      sh('git', ['checkout', '-q', '-b', 'feature'], repoDir)
      writeFileSync(path.join(repoDir, 'feature.txt'), 'x\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'feature work'], repoDir)
      sh('git', ['push', '-u', 'origin', 'feature'], repoDir)

      await expect(isBehindMain('feature', realExec, repoDir)).resolves.toBe(false)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('is true when main has advanced past what the branch was created from', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      sh('git', ['checkout', '-q', '-b', 'feature'], repoDir)
      writeFileSync(path.join(repoDir, 'feature.txt'), 'x\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'feature work'], repoDir)
      sh('git', ['push', '-u', 'origin', 'feature'], repoDir)

      sh('git', ['checkout', '-q', 'main'], repoDir)
      writeFileSync(path.join(repoDir, 'main-moved-on.txt'), 'y\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'main moved on'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      await expect(isBehindMain('feature', realExec, repoDir)).resolves.toBe(true)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})

describe('rebaseAndRetest', () => {
  it('rebases, retests, and pushes the rebased branch when everything passes', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      sh('git', ['checkout', '-q', '-b', 'feature'], repoDir)
      writeFileSync(path.join(repoDir, 'feature.txt'), 'x\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'feature work'], repoDir)
      sh('git', ['push', '-u', 'origin', 'feature'], repoDir)

      sh('git', ['checkout', '-q', 'main'], repoDir)
      writeFileSync(path.join(repoDir, 'main-moved-on.txt'), 'y\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'main moved on'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      const beforeSha = currentRemoteSha(repoDir, 'feature')
      const runTests = vi.fn().mockResolvedValue(undefined)

      const result = await rebaseAndRetest('feature', realExec, repoDir, runTests)

      expect(result).toEqual({ ok: true })
      expect(runTests).toHaveBeenCalledTimes(1)
      const afterSha = currentRemoteSha(repoDir, 'feature')
      expect(afterSha).not.toBe(beforeSha)
      expect(sh('git', ['worktree', 'list'], repoDir)).not.toContain('mr-merge-gate-')
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('does not push and reports the reason when the rebase itself conflicts', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'README.md'), 'hello\nfeature line\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'edit on feature'], repoDir)
      sh('git', ['checkout', '-q', '-b', 'feature'], repoDir)
      sh('git', ['checkout', '-q', 'main'], repoDir)
      sh('git', ['reset', '-q', '--hard', 'HEAD~1'], repoDir)
      writeFileSync(path.join(repoDir, 'README.md'), 'hello\nconflicting main line\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'conflicting edit on main'], repoDir)
      sh('git', ['push', '--force', 'origin', 'main'], repoDir)
      sh('git', ['push', '-u', 'origin', 'feature'], repoDir)

      const beforeSha = currentRemoteSha(repoDir, 'feature')
      const runTests = vi.fn()

      const result = await rebaseAndRetest('feature', realExec, repoDir, runTests)

      expect(result.ok).toBe(false)
      expect(result.reason).toContain('Rebase')
      expect(runTests).not.toHaveBeenCalled()
      expect(currentRemoteSha(repoDir, 'feature')).toBe(beforeSha)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('does not push and reports the reason when tests fail after a clean rebase', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      sh('git', ['checkout', '-q', '-b', 'feature'], repoDir)
      writeFileSync(path.join(repoDir, 'feature.txt'), 'x\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'feature work'], repoDir)
      sh('git', ['push', '-u', 'origin', 'feature'], repoDir)

      sh('git', ['checkout', '-q', 'main'], repoDir)
      writeFileSync(path.join(repoDir, 'main-moved-on.txt'), 'y\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'main moved on'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      const beforeSha = currentRemoteSha(repoDir, 'feature')
      const runTests = vi.fn().mockRejectedValue(new Error('2 tests failed'))

      const result = await rebaseAndRetest('feature', realExec, repoDir, runTests)

      expect(result.ok).toBe(false)
      expect(result.reason).toContain('Tests failed')
      expect(currentRemoteSha(repoDir, 'feature')).toBe(beforeSha)
      expect(sh('git', ['worktree', 'list'], repoDir)).not.toContain('mr-merge-gate-')
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})

describe('_defaultRunTests', () => {
  it('installs dashboard dependencies before running vitest', async () => {
    // Found live 2026-10-01 (PR #119's actual merge attempt): a
    // `git worktree add` scratch checkout has no dashboard/node_modules
    // at all, so `npx vitest run` hard-failed with a dependency-
    // resolution error wall that had nothing to do with the PR's own
    // code -- shown to the user as the re-engagement reason, looking
    // like a real test failure when it was really a missing install step.
    const calls = []
    const exec = vi.fn(async (cmd, args, opts) => {
      calls.push({ cmd, args, cwd: opts?.cwd })
      return { stdout: '', stderr: '' }
    })

    await _defaultRunTests('/repo', exec)

    const dashboardCalls = calls.filter((c) => c.cwd === '/repo/dashboard')
    const installIndex = dashboardCalls.findIndex((c) => c.cmd === 'npm' && c.args[0] === 'install')
    const vitestIndex = dashboardCalls.findIndex((c) => c.cmd === 'npx' && c.args[0] === 'vitest')
    expect(installIndex).toBeGreaterThanOrEqual(0)
    expect(vitestIndex).toBeGreaterThan(installIndex)
  })
})


// ── structured, pipeline-actionable failures (2026-10-02) ───────────────────

import { MergeFailure } from '../webhook-server/failure.js'
import { recordFailure } from '../webhook-server/failure_log.js'
import { recordStage } from '../webhook-server/ticket_stages.js'

const PR = 'https://github.com/G-Eskayo/marvin/pull/71'
const ticketGate = () => vi.fn().mockResolvedValue({ gate: false, headRefName: 'b', body: 'Closes G-Eskayo/marvin#5' })
const ghMergeFails = (err) => vi.fn(async (cmd, args) => { if (args[0] === 'pr' && args[1] === 'merge') throw err; return { stdout: '', stderr: '' } })
const noSleep = { sleep: vi.fn().mockResolvedValue(undefined) }

describe('mergePr structured failures', () => {
  it('throws a MergeFailure carrying code/stage/action for a non-retryable gh failure', async () => {
    const exec = ghMergeFails(Object.assign(new Error('Command failed'), { stderr: 'HTTP 401: Bad credentials' }))
    const p = mergePr(PR, exec, noopRebuild, noopRedispatch, ticketGate(), undefined, undefined, undefined, noSleep)
    await expect(p).rejects.toBeInstanceOf(MergeFailure)
    await p.catch((e) => {
      expect(e.payload).toMatchObject({ code: 'GH_AUTH_INVALID', stage: 'merging', action: 'escalate', retryable: false })
      expect(e.payload.remediation).toContain('.gh-token')
    })
  })

  it('records the failure on the ticket timeline and in the shared failure log', async () => {
    const exec = ghMergeFails(Object.assign(new Error('x'), { stderr: 'HTTP 401: Bad credentials' }))
    await mergePr(PR, exec, noopRebuild, noopRedispatch, ticketGate(), undefined, undefined, undefined, noSleep).catch(() => {})
    expect(recordStage).toHaveBeenCalledWith('5', 'merging', 'failed', expect.stringContaining('GH_AUTH_INVALID'))
    expect(recordFailure).toHaveBeenCalledWith(expect.objectContaining({ ticket: '5', code: 'GH_AUTH_INVALID' }))
  })

  it('retries a transient failure with backoff and then merges', async () => {
    let calls = 0
    const exec = vi.fn(async (cmd, args) => {
      if (args[0] === 'pr' && args[1] === 'merge') {
        calls += 1
        if (calls < 3) throw Object.assign(new Error('x'), { stderr: 'connect ETIMEDOUT' })
      }
      return { stdout: '', stderr: '' }
    })
    const sleep = vi.fn().mockResolvedValue(undefined)
    const result = await mergePr(PR, exec, noopRebuild, noopRedispatch, ticketGate(), undefined, undefined, undefined, { sleep })
    expect(result).toMatchObject({ merged: true })
    expect(calls).toBe(3)
    expect(sleep).toHaveBeenCalledTimes(2)
  })

  it('reports TRANSIENT_NETWORK with the attempt count once the retry budget is spent', async () => {
    const exec = ghMergeFails(Object.assign(new Error('x'), { stderr: 'connect ETIMEDOUT' }))
    const p = mergePr(PR, exec, noopRebuild, noopRedispatch, ticketGate(), undefined, undefined, undefined, noSleep)
    await p.catch((e) => {
      expect(e.payload).toMatchObject({ code: 'TRANSIENT_NETWORK', action: 'retry', attempts: 4 })
    })
    await expect(p).rejects.toBeInstanceOf(MergeFailure)
  })

  it('sends a not-mergeable PR back to its ticket (reengage) instead of just erroring, when a ticket is linked', async () => {
    const exec = ghMergeFails(Object.assign(new Error('x'), { stderr: 'Pull request is not mergeable: merge conflict' }))
    const reengage = vi.fn().mockResolvedValue(undefined)
    const result = await mergePr(PR, exec, noopRebuild, noopRedispatch, ticketGate(), undefined, reengage, undefined, noSleep)
    expect(reengage).toHaveBeenCalledWith(
      expect.objectContaining({ prUrl: PR, ticketNumber: '5', comment: expect.stringContaining('NOT_MERGEABLE') }),
      exec
    )
    expect(result).toMatchObject({ merged: false, reengaged: true, code: 'NOT_MERGEABLE', action: 'reengage' })
  })

  it('does not redispatch or rebuild when the merge failed', async () => {
    const exec = ghMergeFails(Object.assign(new Error('x'), { stderr: 'HTTP 401: Bad credentials' }))
    const rebuild = vi.fn(); const redispatch = vi.fn()
    await mergePr(PR, exec, rebuild, redispatch, ticketGate(), undefined, undefined, undefined, noSleep).catch(() => {})
    expect(rebuild).not.toHaveBeenCalled()
    expect(redispatch).not.toHaveBeenCalled()
  })

  it('still rejects an invalid URL with the original message, now as a coded failure', async () => {
    const p = mergePr('not-a-url', vi.fn())
    await expect(p).rejects.toThrow('Not a GitHub PR URL')
    await p.catch((e) => expect(e.payload.code).toBe('INVALID_REQUEST'))
  })
})
