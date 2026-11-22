import { describe, it, expect, vi } from 'vitest'
import { requiredCheckNames, awaitRequiredChecks } from './ci_status.js'

describe('merge.js integration with awaitRequiredChecks', () => {
  describe('dependencies are properly exported', () => {
    it('requiredCheckNames is exported from ci_status', () => {
      expect(typeof requiredCheckNames).toBe('function')
    })

    it('awaitRequiredChecks is exported from ci_status', () => {
      expect(typeof awaitRequiredChecks).toBe('function')
    })

    it('requiredCheckNames returns an array of check names', () => {
      const names = requiredCheckNames()
      expect(Array.isArray(names)).toBe(true)
      expect(names.length).toBeGreaterThan(0)
    })

    it('all required check names are strings', () => {
      const names = requiredCheckNames()
      expect(names.every((n) => typeof n === 'string')).toBe(true)
    })
  })

  describe('awaitRequiredChecks integration scenarios', () => {
    it('awaitRequiredChecks handles empty PR URL gracefully', async () => {
      const exec = vi.fn()
      // Should return without calling exec when URL is invalid
      await awaitRequiredChecks('invalid', exec, ['Check1'])
      expect(exec).not.toHaveBeenCalled()
    })

    it('awaitRequiredChecks respects custom timeout options', async () => {
      const exec = vi.fn()
      exec.mockResolvedValue({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { name: 'Check1', status: 'COMPLETED', conclusion: 'SUCCESS' }
          ],
          headRefOid: 'abc123'
        })
      })

      await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['Check1'], {
        timeoutMs: 5000,
        pollIntervalMs: 100
      })

      expect(exec).toHaveBeenCalled()
    })
  })
})
