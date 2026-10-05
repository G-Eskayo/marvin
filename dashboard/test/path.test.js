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

import { adoptSharedGhToken } from '../electron/main/path.js'

describe('adoptSharedGhToken', () => {
  it('adopts the shared token file as GH_TOKEN', () => {
    const env = {}
    expect(adoptSharedGhToken(env, () => 'abc\n', '/h')).toBe(true)
    expect(env.GH_TOKEN).toBe('abc')
  })
  it('never overrides an explicit GH_TOKEN', () => {
    const env = { GH_TOKEN: 'mine' }
    expect(adoptSharedGhToken(env, () => 'abc', '/h')).toBe(false)
    expect(env.GH_TOKEN).toBe('mine')
  })
  it('does nothing when the file is missing or empty', () => {
    const env = {}
    expect(adoptSharedGhToken(env, () => { throw new Error('ENOENT') }, '/h')).toBe(false)
    expect(adoptSharedGhToken(env, () => '  \n', '/h')).toBe(false)
    expect(env.GH_TOKEN).toBeUndefined()
  })
})
