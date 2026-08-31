import { describe, it, expect, vi } from 'vitest'
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
  rebaseAndRetest
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

    expect(reengage).toHaveBeenCalledWith(
      {
        prUrl: 'https://github.com/G-Eskayo/marvin/pull/71',
        ticketNumber: '5',
        reasons: ['Regression/quality'],
        comment: 'Tests failed after rebasing onto main:\n\nboom'
      },
      exec
    )
    expect(exec).not.toHaveBeenCalledWith('gh', ['pr', 'merge', 'https://github.com/G-Eskayo/marvin/pull/71', '--merge'])
    expect(rebuild).not.toHaveBeenCalled()
    expect(redispatch).not.toHaveBeenCalled()
    expect(result).toEqual({ merged: false, reengaged: true, reason: 'Tests failed after rebasing onto main:\n\nboom' })
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
