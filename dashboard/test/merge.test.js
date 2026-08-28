import { describe, it, expect, vi } from 'vitest'
import { mergePr, triggerRebuildIfDashboardChanged } from '../webhook-server/merge.js'

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
    const rebuild = vi.fn().mockResolvedValue(undefined)
    await mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec, rebuild)
    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'merge', 'https://github.com/G-Eskayo/marvin/pull/71', '--merge'])
  })

  it('propagates a failure from the underlying gh call', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('merge conflict'))
    await expect(mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec)).rejects.toThrow('merge conflict')
  })

  it('checks for a dashboard rebuild after a successful merge', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '', stderr: '' })
    const rebuild = vi.fn().mockResolvedValue(undefined)
    await mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec, rebuild)
    expect(rebuild).toHaveBeenCalledWith('https://github.com/G-Eskayo/marvin/pull/71', exec)
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
