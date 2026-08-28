import { describe, it, expect, vi } from 'vitest'
import { adoptLoginShellPath } from '../electron/main/path.js'

describe('adoptLoginShellPath', () => {
  it('adopts the PATH returned by the login shell', () => {
    const env = { PATH: '/usr/bin:/bin' }
    const exec = vi.fn().mockReturnValue('/opt/homebrew/bin:/usr/bin:/bin')
    adoptLoginShellPath(env, exec)
    expect(env.PATH).toBe('/opt/homebrew/bin:/usr/bin:/bin')
    expect(exec).toHaveBeenCalledWith('/bin/zsh', ['-ilc', 'echo -n "$PATH"'], expect.objectContaining({ encoding: 'utf8' }))
  })

  it('leaves the existing PATH alone when the shell call throws', () => {
    const env = { PATH: '/usr/bin:/bin' }
    const exec = vi.fn().mockImplementation(() => {
      throw new Error('no such shell')
    })
    adoptLoginShellPath(env, exec)
    expect(env.PATH).toBe('/usr/bin:/bin')
  })

  it('leaves the existing PATH alone when the shell returns empty output', () => {
    const env = { PATH: '/usr/bin:/bin' }
    const exec = vi.fn().mockReturnValue('   ')
    adoptLoginShellPath(env, exec)
    expect(env.PATH).toBe('/usr/bin:/bin')
  })
})
