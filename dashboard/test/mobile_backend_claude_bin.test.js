import { describe, it, expect } from 'vitest'
import { resolveClaudeBin, getCandidates } from '../mobile-backend/claude_bin.js'

describe('claude_bin', () => {
  describe('resolveClaudeBin', () => {
    it('returns binary from which() when found on PATH', () => {
      const fakeWhich = () => '/usr/local/bin/claude'
      const fakeExists = () => false
      const result = resolveClaudeBin(fakeWhich, () => [], fakeExists)
      expect(result).toBe('/usr/local/bin/claude')
    })

    it('tries candidates when which() returns null', () => {
      const fakeWhich = () => null
      const fakeCandidates = () => ['/candidate1', '/candidate2', '/candidate3']
      const fakeExists = (path) => path === '/candidate2'
      const result = resolveClaudeBin(fakeWhich, fakeCandidates, fakeExists)
      expect(result).toBe('/candidate2')
    })

    it('tries candidates when which() throws', () => {
      const fakeWhich = () => {
        throw new Error('which not available')
      }
      const fakeCandidates = () => ['/candidate1', '/candidate2']
      const fakeExists = (path) => path === '/candidate1'
      const result = resolveClaudeBin(fakeWhich, fakeCandidates, fakeExists)
      expect(result).toBe('/candidate1')
    })

    it('throws when binary is not found anywhere', () => {
      const fakeWhich = () => null
      const fakeCandidates = () => ['/notfound1', '/notfound2']
      const fakeExists = () => false
      expect(() => resolveClaudeBin(fakeWhich, fakeCandidates, fakeExists)).toThrow(
        /claude CLI not found/
      )
    })

    it('includes candidate paths in error message', () => {
      const fakeWhich = () => null
      const fakeCandidates = () => ['/home/user/.local/bin/claude', '/opt/homebrew/bin/claude']
      const fakeExists = () => false
      expect(() => resolveClaudeBin(fakeWhich, fakeCandidates, fakeExists)).toThrow(
        /\.local\/bin.*homebrew.*usr\/local/
      )
    })
  })

  describe('getCandidates', () => {
    it('returns default candidates list', () => {
      const candidates = getCandidates()
      expect(candidates).toHaveLength(3)
      expect(candidates[0]).toMatch(/\.local\/bin\/claude$/)
      expect(candidates[1]).toBe('/opt/homebrew/bin/claude')
      expect(candidates[2]).toBe('/usr/local/bin/claude')
    })

    it('includes home directory in first candidate', () => {
      const candidates = getCandidates()
      expect(candidates[0]).toContain(require('os').homedir())
    })
  })
})
