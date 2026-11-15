import { describe, it, expect } from 'vitest'
import { composeOpenMessage } from '../src/components/MarvinButton.jsx'

describe('MarvinButton', () => {
  describe('composeOpenMessage', () => {
    it('returns focused message when session is already open', () => {
      const result = { ok: true, focused: true, dir: '/some/dir' }
      const msg = composeOpenMessage(result)
      expect(msg).toBe('That ticket’s chat was already open, so it’s in front now')
    })

    it('returns opened message with directory when new session', () => {
      const result = { ok: true, focused: false, dir: '/some/dir' }
      const msg = composeOpenMessage(result)
      expect(msg).toContain('Opened in')
      expect(msg).toContain('/some/dir')
    })

    it('redacts home path in directory', () => {
      const result = { ok: true, focused: false, dir: '/Users/gileskayo/.agents/worktree' }
      const msg = composeOpenMessage(result)
      expect(msg).toContain('~')
      expect(msg).not.toContain('/Users/gileskayo')
    })

    it('returns error message when result is not ok', () => {
      const result = { ok: false, error: 'Custom error' }
      const msg = composeOpenMessage(result)
      expect(msg).toBe('Custom error')
    })

    it('returns generic error when no error message provided', () => {
      const result = { ok: false }
      const msg = composeOpenMessage(result)
      expect(msg).toBe('Could not open a session')
    })

    it('handles null result', () => {
      const msg = composeOpenMessage(null)
      expect(msg).toBe('Could not open a session')
    })

    it('handles result with error field', () => {
      const result = { ok: false, error: 'Connection timeout' }
      const msg = composeOpenMessage(result)
      expect(msg).toBe('Connection timeout')
    })
  })
})
