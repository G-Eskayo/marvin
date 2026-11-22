import { describe, it, expect, vi } from 'vitest'
import { requiredCheckNames, gateCheckNames, awaitRequiredChecks, REQUIRED_CHECKS_TIMEOUT_MS } from './ci_status.js'
import { MergeFailure } from './failure.js'

describe('ci_status', () => {
  describe('requiredCheckNames', () => {
    it('returns all required check names from required-checks.json', () => {
      const result = requiredCheckNames()
      expect(Array.isArray(result)).toBe(true)
      expect(result.length).toBeGreaterThan(0)
      expect(result).toContain('Rules')
      expect(result).toContain('Python tests')
      expect(result).toContain('Dashboard unit tests')
      expect(result).toContain('Secret and transcript scan')
    })

    it('returns empty array when file is unreadable', () => {
      const result = requiredCheckNames('/nonexistent/path')
      expect(result).toEqual([])
    })
  })

  describe('gateCheckNames', () => {
    it('returns gate check names (excluding CI-only checks)', () => {
      const result = gateCheckNames()
      expect(Array.isArray(result)).toBe(true)
      // Should include checks with where='both' or no where field (default is 'both')
      expect(result).toContain('Rules')
      expect(result).toContain('Python tests')
      // Secret scan has no 'where' specified so it defaults to 'both'
    })

    it('returns empty array when file is unreadable', () => {
      const result = gateCheckNames('/nonexistent/path')
      expect(result).toEqual([])
    })

    it('extracts shared logic via readRequiredChecks', () => {
      const gate = gateCheckNames()
      const all = requiredCheckNames()
      // Both should be arrays
      expect(Array.isArray(gate)).toBe(true)
      expect(Array.isArray(all)).toBe(true)
      // Gate names should be a subset of all (or equal)
      expect(gate.every((n) => all.includes(n))).toBe(true)
    })
  })

  describe('awaitRequiredChecks', () => {
    it('returns immediately when names array is empty', async () => {
      const exec = vi.fn()
      await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, [])
      expect(exec).not.toHaveBeenCalled()
    })

    it('returns immediately when names is not an array', async () => {
      const exec = vi.fn()
      await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, null)
      expect(exec).not.toHaveBeenCalled()
    })

    it('returns immediately on invalid PR URL', async () => {
      const exec = vi.fn()
      await awaitRequiredChecks('not-a-url', exec, ['Check1'])
      expect(exec).not.toHaveBeenCalled()
    })

    it('polls until required checks pass', async () => {
      const exec = vi.fn()
      exec.mockResolvedValueOnce({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { name: 'Check1', status: 'IN_PROGRESS', conclusion: null },
            { name: 'Check2', status: 'COMPLETED', conclusion: 'SUCCESS' }
          ],
          headRefOid: 'abc123'
        })
      })
      exec.mockResolvedValueOnce({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { name: 'Check1', status: 'COMPLETED', conclusion: 'SUCCESS' },
            { name: 'Check2', status: 'COMPLETED', conclusion: 'SUCCESS' }
          ],
          headRefOid: 'abc123'
        })
      })

      await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['Check1', 'Check2'], { timeoutMs: 30_000, pollIntervalMs: 100 })
      expect(exec.mock.calls.length).toBe(2)
    })

    it('throws CI_FAILED when required checks fail', async () => {
      const exec = vi.fn()
      exec.mockResolvedValue({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { name: 'Check1', status: 'COMPLETED', conclusion: 'FAILURE' },
            { name: 'Check2', status: 'COMPLETED', conclusion: 'SUCCESS' }
          ],
          headRefOid: 'abc123'
        })
      })

      await expect(
        awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['Check1', 'Check2'])
      ).rejects.toThrow(MergeFailure)

      const error = await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['Check1', 'Check2']).catch((e) => e)
      expect(error.payload.code).toBe('CI_FAILED')
      expect(error.payload.message).toContain('Check1')
      expect(error.payload.action).toBe('reengage')
    })

    it('throws HEAD_MOVED when PR head changes during poll', async () => {
      const exec = vi.fn()
      exec.mockResolvedValueOnce({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { name: 'Check1', status: 'IN_PROGRESS', conclusion: null }
          ],
          headRefOid: 'abc123'
        })
      })
      exec.mockResolvedValueOnce({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { name: 'Check1', status: 'IN_PROGRESS', conclusion: null }
          ],
          headRefOid: 'def456'
        })
      })

      const error = await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['Check1'], { timeoutMs: 30_000, pollIntervalMs: 100 }).catch((e) => e)
      expect(error.payload.code).toBe('HEAD_MOVED')
    })

    it('throws CI_TIMEOUT when checks do not finish within deadline', async () => {
      const exec = vi.fn()
      exec.mockResolvedValue({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { name: 'Check1', status: 'IN_PROGRESS', conclusion: null }
          ],
          headRefOid: 'abc123'
        })
      })

      const error = await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['Check1'], { timeoutMs: 100, pollIntervalMs: 50 }).catch((e) => e)
      expect(error.payload.code).toBe('CI_TIMEOUT')
      expect(error.payload.message).toContain('did not finish')
    })

    it('fails open when network error occurs before first successful read', async () => {
      const exec = vi.fn()
      exec.mockRejectedValue(new Error('Network error'))

      // Should return without throwing
      await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['Check1'], { timeoutMs: 100, pollIntervalMs: 50 })
      // If we got here without an exception, the test passed
      expect(true).toBe(true)
    })

    it('throws CI_TIMEOUT when network error occurs after first successful read', async () => {
      const exec = vi.fn()
      exec.mockResolvedValueOnce({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { name: 'Check1', status: 'IN_PROGRESS', conclusion: null }
          ],
          headRefOid: 'abc123'
        })
      })
      exec.mockRejectedValue(new Error('Network error'))

      const error = await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['Check1'], { timeoutMs: 100, pollIntervalMs: 50 }).catch((e) => e)
      expect(error.payload.code).toBe('CI_TIMEOUT')
    })

    it('only checks named required checks, ignoring others', async () => {
      const exec = vi.fn()
      exec.mockResolvedValue({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { name: 'Check1', status: 'COMPLETED', conclusion: 'SUCCESS' },
            { name: 'Check2', status: 'COMPLETED', conclusion: 'FAILURE' }
          ],
          headRefOid: 'abc123'
        })
      })

      // Check2 is failing, but we only care about Check1
      await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['Check1'])
      expect(true).toBe(true)
    })

    it('classifies pending status as not-yet-done', async () => {
      const exec = vi.fn()
      let callCount = 0
      exec.mockImplementation(() => {
        callCount++
        if (callCount === 1) {
          return Promise.resolve({
            stdout: JSON.stringify({
              statusCheckRollup: [
                { name: 'Check1', status: 'PENDING', conclusion: null }
              ],
              headRefOid: 'abc123'
            })
          })
        } else {
          return Promise.resolve({
            stdout: JSON.stringify({
              statusCheckRollup: [
                { name: 'Check1', status: 'COMPLETED', conclusion: 'SUCCESS' }
              ],
              headRefOid: 'abc123'
            })
          })
        }
      })

      await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['Check1'], { timeoutMs: 30_000, pollIntervalMs: 100 })
      expect(exec.mock.calls.length).toBeGreaterThan(1)
    })

    it('handles status context (old format) checks', async () => {
      const exec = vi.fn()
      exec.mockResolvedValueOnce({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { __typename: 'StatusContext', context: 'ci/test', state: 'PENDING' }
          ],
          headRefOid: 'abc123'
        })
      })
      exec.mockResolvedValueOnce({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { __typename: 'StatusContext', context: 'ci/test', state: 'SUCCESS' }
          ],
          headRefOid: 'abc123'
        })
      })

      await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['ci/test'], { timeoutMs: 30_000, pollIntervalMs: 100 })
      expect(exec.mock.calls.length).toBe(2)
    })

    it('case-sensitive check name matching', async () => {
      const exec = vi.fn()
      exec.mockResolvedValue({
        stdout: JSON.stringify({
          statusCheckRollup: [
            { name: 'Check1', status: 'COMPLETED', conclusion: 'SUCCESS' }
          ],
          headRefOid: 'abc123'
        })
      })

      // Case mismatch should still wait (check1 != Check1) until timeout
      const error = await awaitRequiredChecks('https://github.com/G-Eskayo/marvin/pull/1', exec, ['check1'], { timeoutMs: 100, pollIntervalMs: 50 }).catch((e) => e)
      // Should timeout because check1 never completes (only Check1 exists)
      expect(error.payload?.code).toBe('CI_TIMEOUT')
    })
  })
})
