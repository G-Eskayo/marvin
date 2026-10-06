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
  defaultGateContext,
  _defaultRunTests,
  assertTargetsBase
} from '../webhook-server/merge.js'
import { MergeFailure, refusal, summarizeGateFailure } from '../webhook-server/failure.js'

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

describe('rebaseAndRetest with generated-file conflict resolution', () => {
  // README.md stands in for a generated file: it conflicts between the branch and main.
  function conflictFixture() {
    const f = makeGitFixture()
    const { repoDir } = f
    sh('git', ['checkout', '-q', '-b', 'feature'], repoDir)
    writeFileSync(path.join(repoDir, 'README.md'), 'hello\nfeature line\n')
    sh('git', ['add', '.'], repoDir)
    sh('git', ['commit', '-q', '-m', 'edit on feature'], repoDir)
    sh('git', ['push', '-u', 'origin', 'feature'], repoDir)
    sh('git', ['checkout', '-q', 'main'], repoDir)
    writeFileSync(path.join(repoDir, 'README.md'), 'hello\nmain line\n')
    sh('git', ['add', '.'], repoDir)
    sh('git', ['commit', '-q', '-m', 'edit on main'], repoDir)
    sh('git', ['push', 'origin', 'main'], repoDir)
    return f
  }

  it('lets the resolver finish a conflicted rebase, then retests and pushes', async () => {
    const { root, repoDir } = conflictFixture()
    try {
      const before = currentRemoteSha(repoDir, 'feature')
      const resolve = vi.fn(async (dir) => {
        sh('git', ['checkout', '--ours', '--', 'README.md'], dir)
        sh('git', ['add', 'README.md'], dir)
        await realExec('git', ['rebase', '--continue'], { cwd: dir, env: { ...process.env, GIT_EDITOR: 'true' } })
        return { ok: true }
      })
      const runTests = vi.fn().mockResolvedValue(undefined)
      const result = await rebaseAndRetest('feature', realExec, repoDir, runTests, 'main', resolve)
      expect(result).toEqual({ ok: true })
      expect(resolve).toHaveBeenCalledTimes(1)
      expect(runTests).toHaveBeenCalledTimes(1)
      expect(currentRemoteSha(repoDir, 'feature')).not.toBe(before)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('fails with the resolver\'s reason, pushes nothing and cleans up when it cannot resolve', async () => {
    const { root, repoDir } = conflictFixture()
    try {
      const before = currentRemoteSha(repoDir, 'feature')
      const resolve = vi.fn().mockResolvedValue({ ok: false, reason: 'conflicts in files that are not generated: src.js' })
      const runTests = vi.fn()
      const result = await rebaseAndRetest('feature', realExec, repoDir, runTests, 'main', resolve)
      expect(result.ok).toBe(false)
      expect(result.reason).toContain('not generated: src.js')
      expect(runTests).not.toHaveBeenCalled()
      expect(currentRemoteSha(repoDir, 'feature')).toBe(before)
      expect(sh('git', ['worktree', 'list'], repoDir)).not.toContain('mr-merge-gate-')
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

// ── another project's PR (execution profile) ────────────────────────────────

const CC_PR = 'https://github.com/G-Eskayo/clarity-captions/pull/21'
const CTX = { repo: 'G-Eskayo/clarity-captions', clone: '/Users/me/Developer/clarity-captions', base: 'main', runTests: vi.fn() }

describe('mergePr for a project with a profile', () => {
  it('refuses a project that has no profile or has not opted in, without merging or sending anything back', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const reengage = vi.fn()
    const gateContext = vi.fn().mockRejectedValue(new MergeFailure(refusal('NO_MERGE_PROFILE', 'request', 'no profile', 'Add one.')))
    await expect(mergePr(CC_PR, exec, noopRebuild, noopRedispatch, vi.fn(), vi.fn(), reengage, vi.fn(), { gateContext })).rejects.toMatchObject({ payload: { code: 'NO_MERGE_PROFILE' } })
    expect(exec).not.toHaveBeenCalledWith('gh', ['pr', 'merge', CC_PR, '--merge'])
    expect(reengage).not.toHaveBeenCalled()
  })

  it('merges directly when the PR is not behind, and does not rebuild the dashboard', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const rebuild = vi.fn()
    const shouldGateMerge = vi.fn().mockResolvedValue({ gate: false, headRefName: 'pipeline/x', body: 'Closes G-Eskayo/clarity-captions#7' })
    const result = await mergePr(CC_PR, exec, rebuild, noopRedispatch, shouldGateMerge, vi.fn(), vi.fn(), vi.fn(), { gateContext: async () => CTX })
    expect(shouldGateMerge).toHaveBeenCalledWith(CC_PR, exec, CTX)
    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'merge', CC_PR, '--merge'])
    expect(rebuild).not.toHaveBeenCalled()
    expect(result.merged).toBe(true)
  })

  it('rebases and retests in the project\'s clone on its base branch with its own checks when behind', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const shouldGateMerge = vi.fn().mockResolvedValue({ gate: true, headRefName: 'pipeline/g-eskayo/clarity-captions#7', body: 'Closes G-Eskayo/clarity-captions#7' })
    const rebaseAndRetestFn = vi.fn().mockResolvedValue({ ok: true })
    await mergePr(CC_PR, exec, noopRebuild, noopRedispatch, shouldGateMerge, rebaseAndRetestFn, vi.fn(), vi.fn(), { gateContext: async () => CTX })
    expect(rebaseAndRetestFn).toHaveBeenCalledWith('pipeline/g-eskayo/clarity-captions#7', exec, CTX.clone, CTX.runTests, 'main', CTX.resolveConflicts)
  })

  it('records the ticket timeline under the project, not under marvin\'s same-numbered ticket', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const shouldGateMerge = vi.fn().mockResolvedValue({ gate: true, headRefName: 'b', body: 'Closes G-Eskayo/clarity-captions#7' })
    const recordStageFn = vi.fn()
    await mergePr(CC_PR, exec, noopRebuild, noopRedispatch, shouldGateMerge, vi.fn().mockResolvedValue({ ok: true }), vi.fn(), recordStageFn, { gateContext: async () => CTX })
    const stages = recordStageFn.mock.calls.map(([, stage, status]) => `${stage}:${status}`)
    expect(stages).toEqual(['gate:started', 'gate:passed', 'merging:started', 'merging:passed', 'done:passed'])  // no dashboard rebuild stage
    expect(recordStageFn.mock.calls.every((c) => c[4]?.repo === 'G-Eskayo/clarity-captions')).toBe(true)
  })

  it('sends a failed retest back to the ticket in that project\'s repo with the failing test named', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const shouldGateMerge = vi.fn().mockResolvedValue({ gate: true, headRefName: 'b', body: 'Closes G-Eskayo/clarity-captions#7' })
    const failing = { ok: false, reason: "Tests failed after rebasing onto main:\n\nTest Case '-[CoreTests.AlignTests testBad]' failed (0.1 seconds)." }
    const reengage = vi.fn()
    const result = await mergePr(CC_PR, exec, noopRebuild, noopRedispatch, shouldGateMerge, vi.fn().mockResolvedValue(failing), reengage, vi.fn(), { gateContext: async () => CTX })
    expect(result).toMatchObject({ merged: false, reengaged: true, code: 'GATE_TESTS_FAILED' })
    expect(reengage.mock.calls[0][0]).toMatchObject({ prUrl: CC_PR, ticketNumber: '7' })
    expect(reengage.mock.calls[0][0].comment).toContain('CoreTests.AlignTests/testBad')
  })
})

describe('defaultGateContext', () => {
  const run = (info) => vi.fn().mockResolvedValue({ stdout: JSON.stringify(info), stderr: '' })

  it('refuses a project with no profile, or one that has not opted in', async () => {
    await expect(defaultGateContext('o/x', run({ profile: false }))).rejects.toMatchObject({ payload: { code: 'NO_MERGE_PROFILE' } })
    await expect(defaultGateContext('o/x', run({ repo: 'o/x', clone: '/c', base_branch: 'main', merge_from_dashboard: false, missing_here: [] }))).rejects.toMatchObject({ payload: { code: 'NO_MERGE_PROFILE' } })
  })

  it('refuses when this machine lacks a tool the required checks need, as an environment problem', async () => {
    const err = await defaultGateContext('o/x', run({ repo: 'o/x', clone: '/c', base_branch: 'main', merge_from_dashboard: true, missing_here: ['xcode'] })).catch((e) => e)
    expect(err.payload).toMatchObject({ code: 'ENV_MISSING', action: 'escalate' })
    expect(err.payload.message).toContain('xcode')
  })

  it('refuses when there is no clone of the project on this machine', async () => {
    await expect(defaultGateContext('o/x', run({ repo: 'o/x', clone: null, base_branch: 'main', merge_from_dashboard: true, missing_here: [] }))).rejects.toMatchObject({ payload: { code: 'NO_MERGE_PROFILE' } })
  })

  it('hands back the clone, base branch and a runner that verifies with the profile', async () => {
    const exec = run({ repo: 'o/x', clone: '/c', base_branch: 'trunk', merge_from_dashboard: true, missing_here: [] })
    const ctx = await defaultGateContext('o/x', exec)
    expect(ctx).toMatchObject({ repo: 'o/x', clone: '/c', base: 'trunk' })
    await ctx.runTests('/scratch', exec)
    const last = exec.mock.calls.at(-1)
    expect(last[1].slice(-3)).toEqual(['verify', 'o/x', '/scratch'])
  })
})

describe('base branches other than main', () => {
  it('isBehindMain compares against the given base', async () => {
    const calls = []
    const exec = vi.fn(async (cmd, args) => {
      calls.push(args.join(' '))
      return { stdout: '', stderr: '' }
    })
    await isBehindMain('feature', exec, '/repo', 'trunk')
    expect(calls[0]).toBe('fetch origin trunk feature')
    expect(calls[1]).toContain('origin/trunk')
  })

  it('rebaseAndRetest rebases onto the given base and pushes, in a real repo', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      sh('git', ['branch', '-m', 'main', 'trunk'], repoDir)
      sh('git', ['push', '-u', 'origin', 'trunk'], repoDir)
      sh('git', ['checkout', '-q', '-b', 'feature'], repoDir)
      writeFileSync(path.join(repoDir, 'f.txt'), 'x\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'feature'], repoDir)
      sh('git', ['push', '-u', 'origin', 'feature'], repoDir)
      sh('git', ['checkout', '-q', 'trunk'], repoDir)
      writeFileSync(path.join(repoDir, 't.txt'), 'y\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'trunk moved'], repoDir)
      sh('git', ['push', 'origin', 'trunk'], repoDir)
      const runTests = vi.fn().mockResolvedValue(undefined)
      const result = await rebaseAndRetest('feature', realExec, repoDir, runTests, 'trunk')
      expect(result).toEqual({ ok: true })
      expect(runTests).toHaveBeenCalledTimes(1)
      sh('git', ['fetch', 'origin', 'feature'], repoDir)
      expect(sh('git', ['merge-base', '--is-ancestor', 'origin/trunk', 'origin/feature'], repoDir)).toBe('')
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})

describe('a PR must target the project base branch', () => {
  const PR = 'https://github.com/G-Eskayo/finance-os/pull/8'
  const viewing = (base) => vi.fn().mockResolvedValue({ stdout: JSON.stringify({ baseRefName: base }) })

  it('refuses a PR aimed at a side branch: GitHub would "merge" it there and it would never reach main', async () => {
    await expect(assertTargetsBase(PR, viewing('feature/bills-table'), 'main')).rejects.toMatchObject({
      payload: { code: 'WRONG_BASE', action: 'escalate' }
    })
    await expect(assertTargetsBase(PR, viewing('feature/bills-table'), 'main')).rejects.toMatchObject({
      payload: { message: expect.stringContaining('feature/bills-table') }
    })
  })

  it('passes a PR aimed at the base branch, and uses the profile base, not a hardcoded main', async () => {
    await expect(assertTargetsBase(PR, viewing('main'), 'main')).resolves.toBeUndefined()
    await expect(assertTargetsBase(PR, viewing('develop'), 'develop')).resolves.toBeUndefined()
  })

  it('does not block on a metadata hiccup (the merge itself would fail loudly anyway)', async () => {
    await expect(assertTargetsBase(PR, vi.fn().mockRejectedValue(new Error('boom')), 'main')).resolves.toBeUndefined()
    await expect(assertTargetsBase(PR, vi.fn().mockResolvedValue({ stdout: 'not json' }), 'main')).resolves.toBeUndefined()
  })

  it('mergePr refuses before merging anything', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: JSON.stringify({ baseRefName: 'feature/x' }) })
    await expect(mergePr('https://github.com/G-Eskayo/marvin/pull/9', exec, noopRebuild, noopRedispatch)).rejects.toMatchObject({ payload: { code: 'WRONG_BASE' } })
    expect(exec.mock.calls.some((c) => c[1]?.includes('merge'))).toBe(false)
  })
})

describe('merges are serialized per repo (a merge queue of one)', () => {
  const A1 = 'https://github.com/G-Eskayo/clarity-captions/pull/1'
  const A2 = 'https://github.com/G-Eskayo/clarity-captions/pull/2'
  const B1 = 'https://github.com/G-Eskayo/finance-os/pull/1'

  // An exec whose `gh pr merge` call stays open until released, recording what was in flight at the same time.
  function slowMerges() {
    const state = { active: 0, maxActive: 0, order: [] }
    const exec = vi.fn(async (cmd, args) => {
      if (cmd === 'gh' && args[1] === 'merge') {
        state.order.push(args[2])
        state.active += 1
        state.maxActive = Math.max(state.maxActive, state.active)
        await new Promise((r) => setTimeout(r, 25))
        state.active -= 1
      }
      return { stdout: JSON.stringify({ baseRefName: 'main' }), stderr: '' }
    })
    return { state, exec }
  }
  const run = (url, exec) => mergePr(url, exec, noopRebuild, noopRedispatch, vi.fn().mockResolvedValue({ gate: false, headRefName: 'x', body: '' }), vi.fn(), vi.fn(), vi.fn(), { gateContext: async () => ({ repo: 'r', clone: '/c', base: 'main', runTests: vi.fn() }) })

  it('two merges in the same repo never run at the same time, and keep their order', async () => {
    const { state, exec } = slowMerges()
    await Promise.all([run(A1, exec), run(A2, exec)])
    expect(state.maxActive).toBe(1)
    expect(state.order).toEqual([A1, A2])
  })

  it('merges in different repos do not wait for each other', async () => {
    const { state, exec } = slowMerges()
    await Promise.all([run(A1, exec), run(B1, exec)])
    expect(state.maxActive).toBe(2)
  })

  it('a failed merge does not block the ones queued behind it', async () => {
    const exec = vi.fn(async (cmd, args) => {
      if (cmd === 'gh' && args[1] === 'merge' && args[2] === A1) throw new Error('boom')
      return { stdout: JSON.stringify({ baseRefName: 'main' }), stderr: '' }
    })
    const results = await Promise.allSettled([run(A1, exec), run(A2, exec)])
    expect(results[0].status).toBe('rejected')
    expect(results[1].status).toBe('fulfilled')
  })
})

describe('a build-machine failure is not a code failure', () => {
  const PR = 'https://github.com/G-Eskayo/clarity-captions/pull/49'
  const CTX2 = { repo: 'G-Eskayo/clarity-captions', clone: '/c', base: 'main', runTests: vi.fn(), resolveConflicts: null }

  it('classifies infrastructure signatures as GATE_INFRA, real test failures as GATE_TESTS_FAILED', () => {
    expect(summarizeGateFailure('Tests failed after rebasing onto main:\n\nerror: unable to attach DB: accessing build database: database is locked').code).toBe('GATE_INFRA')
    expect(summarizeGateFailure('Tests failed after rebasing onto main:\n\nERROR: No space left on device').code).toBe('GATE_INFRA')
    expect(summarizeGateFailure('Tests failed after rebasing onto main:\n\nFinanceOS unit tests (npm test) cannot run: this project has no test command yet').code).toBe('GATE_INFRA')
    expect(summarizeGateFailure('Tests failed after rebasing onto main:\n\nFAILED test/a.test.js::adds').code).toBe('GATE_TESTS_FAILED')
    expect(summarizeGateFailure('Rebase onto main failed:\n\nCONFLICT').code).toBe('REBASE_CONFLICT')
  })

  it('refuses without sending the ticket back, so the PR can simply be approved again', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: JSON.stringify({ baseRefName: 'main' }), stderr: '' })
    const reengage = vi.fn()
    const gate = vi.fn().mockResolvedValue({ gate: true, headRefName: 'pipeline/x', body: 'Closes G-Eskayo/clarity-captions#35' })
    const rebase = vi.fn().mockResolvedValue({ ok: false, reason: 'Tests failed after rebasing onto main:\n\nerror: database is locked' })
    await expect(mergePr(PR, exec, noopRebuild, noopRedispatch, gate, rebase, reengage, vi.fn(), { gateContext: async () => CTX2 }))
      .rejects.toMatchObject({ payload: { code: 'GATE_INFRA', action: 'escalate' } })
    expect(reengage).not.toHaveBeenCalled()
    expect(exec).not.toHaveBeenCalledWith('gh', ['pr', 'merge', PR, '--merge'])
  })

  it('still sends a genuinely failing PR back', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: JSON.stringify({ baseRefName: 'main' }), stderr: '' })
    const reengage = vi.fn().mockResolvedValue(undefined)
    const gate = vi.fn().mockResolvedValue({ gate: true, headRefName: 'pipeline/x', body: 'Closes G-Eskayo/clarity-captions#35' })
    const rebase = vi.fn().mockResolvedValue({ ok: false, reason: 'Tests failed after rebasing onto main:\n\nFAILED test/a.test.js::adds' })
    const result = await mergePr(PR, exec, noopRebuild, noopRedispatch, gate, rebase, reengage, vi.fn(), { gateContext: async () => CTX2 })
    expect(result.reengaged).toBe(true)
    expect(reengage).toHaveBeenCalledTimes(1)
  })
})

describe('merging waits for the repo\'s own CI', () => {
  const PR = 'https://github.com/G-Eskayo/clarity-captions/pull/57'
  const CTX3 = { repo: 'G-Eskayo/clarity-captions', clone: '/c', base: 'main', runTests: vi.fn(), resolveConflicts: null }
  const gate = () => vi.fn().mockResolvedValue({ gate: false, headRefName: 'pipeline/x', body: 'Closes G-Eskayo/clarity-captions#35' })
  const execWith = (rollup) => vi.fn(async (cmd, args) => ({ stdout: JSON.stringify({ baseRefName: 'main', statusCheckRollup: rollup }), stderr: '' }))
  const go = (exec, reengage = vi.fn().mockResolvedValue(undefined)) =>
    mergePr(PR, exec, noopRebuild, noopRedispatch, gate(), vi.fn(), reengage, vi.fn(), { gateContext: async () => CTX3 })

  it('failing checks send the PR back with the check names, and merge nothing', async () => {
    const exec = execWith([{ __typename: 'CheckRun', name: 'CaptionCore unit tests', status: 'COMPLETED', conclusion: 'FAILURE' }])
    const reengage = vi.fn().mockResolvedValue(undefined)
    const result = await go(exec, reengage)
    expect(result).toMatchObject({ merged: false, reengaged: true, code: 'CI_FAILED' })
    expect(reengage).toHaveBeenCalledWith(expect.objectContaining({ prUrl: PR, ticketNumber: 35, comment: expect.stringContaining('CaptionCore unit tests') }), exec)
    expect(exec).not.toHaveBeenCalledWith('gh', ['pr', 'merge', PR, '--merge'])
  })

  it('running checks refuse without sending it back', async () => {
    const reengage = vi.fn()
    await expect(go(execWith([{ __typename: 'CheckRun', name: 'build', status: 'IN_PROGRESS', conclusion: null }]), reengage))
      .rejects.toMatchObject({ payload: { code: 'CI_PENDING' } })
    expect(reengage).not.toHaveBeenCalled()
  })

  it('passing checks, or none at all, merge as before', async () => {
    for (const rollup of [[{ __typename: 'CheckRun', name: 'a', status: 'COMPLETED', conclusion: 'SUCCESS' }], []]) {
      const exec = execWith(rollup)
      const result = await go(exec)
      expect(result.merged).toBe(true)
      expect(exec).toHaveBeenCalledWith('gh', ['pr', 'merge', PR, '--merge'])
    }
  })
})
