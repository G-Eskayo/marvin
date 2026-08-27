import { describe, it, expect, vi } from 'vitest'
import { mergePr } from '../webhook-server/merge.js'

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
    await mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec)
    expect(exec).toHaveBeenCalledWith('gh', ['pr', 'merge', 'https://github.com/G-Eskayo/marvin/pull/71', '--merge'])
  })

  it('propagates a failure from the underlying gh call', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('merge conflict'))
    await expect(mergePr('https://github.com/G-Eskayo/marvin/pull/71', exec)).rejects.toThrow('merge conflict')
  })
})
