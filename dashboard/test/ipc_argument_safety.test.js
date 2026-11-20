import { describe, it, expect } from 'vitest'
import path from 'path'
import { checkShowPath } from '../electron/main/show.js'

// Ticket #1216: IPC handlers that work with file paths must validate arguments
// to prevent path traversal attacks, even with a sandboxed renderer.

describe('checkShowPath: path argument type validation', () => {
  const roots = ['/Users/test/allowed']

  it('rejects undefined, null, and non-string arguments', () => {
    expect(checkShowPath(undefined, { roots })).toMatchObject({ ok: false })
    expect(checkShowPath(null, { roots })).toMatchObject({ ok: false })
    expect(checkShowPath(123, { roots })).toMatchObject({ ok: false })
    expect(checkShowPath([], { roots })).toMatchObject({ ok: false })
    expect(checkShowPath({}, { roots })).toMatchObject({ ok: false })
  })

  it('rejects empty and whitespace-only strings', () => {
    expect(checkShowPath('', { roots })).toMatchObject({ ok: false })
    expect(checkShowPath('  ', { roots })).toMatchObject({ ok: false })
  })

  it('rejects relative paths', () => {
    expect(checkShowPath('./file.txt', { roots })).toMatchObject({ ok: false })
    expect(checkShowPath('../etc/passwd', { roots })).toMatchObject({ ok: false })
  })

  it('rejects paths with null bytes', () => {
    expect(checkShowPath('/Users/test/file.txt\0.sh', { roots })).toMatchObject({ ok: false })
  })
})

describe('checkShowPath: containment validation', () => {
  it('rejects paths outside allowed roots', () => {
    const result = checkShowPath('/etc/passwd', { roots: ['/Users/test/allowed'] })
    expect(result.ok).toBe(false)
  })

  it('rejects relative paths', () => {
    const result = checkShowPath('./docs/file.txt', { roots: ['/Users/test/allowed'] })
    expect(result.ok).toBe(false)
  })

  it('rejects oversized paths (>= 10MB) and asserts rejection', () => {
    const huge = 'x'.repeat(10 * 1024 * 1024)
    const result = checkShowPath(huge, { roots: ['/Users/test/allowed'] })
    expect(result).toHaveProperty('ok', false)
  })

  it('rejects secret files by name pattern (.env, .gh-token, id_rsa, etc.) - pattern check', () => {
    // Use mocked realpath and stat to test the secret-name pattern without needing real files
    const secretPatterns = ['.env', '.env.local', '.gh-token', '.netrc', 'id_rsa', 'id_ed25519.pem', 'cert.p12']

    const mockRealpath = (p) => p
    const mockStat = (p) => ({ isFile: () => true })

    for (const pattern of secretPatterns) {
      const file = path.join('/Users/test/allowed', pattern)
      const result = checkShowPath(file, { roots: ['/Users/test/allowed'], realpath: mockRealpath, stat: mockStat })
      expect(result).toMatchObject({ ok: false })
    }
  })

  it('rejects paths inside secret directories (.ssh, .gnupg, .aws)', () => {
    const secretDirs = ['.ssh', '.gnupg', '.aws']

    const mockRealpath = (p) => p
    const mockStat = (p) => ({ isFile: () => true })

    for (const dir of secretDirs) {
      const file = path.join('/Users/test/allowed', dir, 'private-key')
      const result = checkShowPath(file, { roots: ['/Users/test/allowed'], realpath: mockRealpath, stat: mockStat })
      expect(result).toMatchObject({ ok: false })
    }
  })

  it('rejects symlinks pointing outside allowed roots - with mocked realpath', () => {
    const mockRealpath = (p) => {
      if (p.includes('link-to-secret')) return '/etc/passwd'
      return p
    }
    const mockStat = (p) => ({ isFile: () => true })

    const link = path.join('/Users/test/allowed', 'link-to-secret')
    const result = checkShowPath(link, { roots: ['/Users/test/allowed'], realpath: mockRealpath, stat: mockStat })
    expect(result.ok).toBe(false)
  })
})

describe('IPC handler argument safety patterns', () => {
  it('real IPC handlers must type-check path arguments before validation', () => {
    const allowedDir = '/Users/test/allowed'
    const mockRealpath = (p) => p
    const mockStat = (p) => ({ isFile: () => true })

    // Simulates a safe handler pattern that handlers in show.js, outbox.js, etc. should follow.
    const safeHandler = (argPath) => {
      // Type check first: reject non-strings without coercion
      if (typeof argPath !== 'string') throw new Error('Expected a string path')
      const result = checkShowPath(argPath, { roots: [allowedDir], realpath: mockRealpath, stat: mockStat })
      if (!result.ok) throw new Error(result.reason)
      return result.real
    }

    // Type errors should throw immediately.
    expect(() => safeHandler(undefined)).toThrow(/Expected a string/)
    expect(() => safeHandler(123)).toThrow(/Expected a string/)
    expect(() => safeHandler({})).toThrow(/Expected a string/)

    // Valid file paths (within allowed roots) should succeed.
    const file = path.join(allowedDir, 'valid.txt')
    expect(safeHandler(file)).toBe(file)

    // Invalid paths should fail validation.
    expect(() => safeHandler('/etc/passwd')).toThrow()
  })
})
