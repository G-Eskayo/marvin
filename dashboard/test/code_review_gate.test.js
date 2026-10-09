import { describe, it, expect, vi } from 'vitest'
import { assertCodeReviewClean } from '../webhook-server/code_review_gate.js'
import { MergeFailure } from '../webhook-server/failure.js'

describe('assertCodeReviewClean', () => {
  const PR = 'https://github.com/G-Eskayo/marvin/pull/96'
  const scriptPath = '/fake/code_review_gate.py'

  // Test 13: Clean review → resolves
  it('clean review resolves without error', async () => {
    const exec = vi.fn().mockResolvedValue({
      stdout: JSON.stringify({ clean: true, findings: [] })
    })
    await expect(assertCodeReviewClean(PR, exec, scriptPath)).resolves.toBeUndefined()
  })

  // Test 14: Findings found → rejects with CODE_REVIEW_FOUND, action: reengage
  it('findings block merge and reengage the PR', async () => {
    const exec = vi.fn().mockResolvedValue({
      stdout: JSON.stringify({
        clean: false,
        findings: [
          "lib/foo.py:42 — unused variable x",
          "lib/bar.py:10 — missing type annotation"
        ]
      })
    })
    await expect(assertCodeReviewClean(PR, exec, scriptPath)).rejects.toMatchObject({
      payload: {
        code: 'CODE_REVIEW_FOUND',
        action: 'reengage',
        message: expect.stringContaining('lib/foo.py:42')
      }
    })
  })

  // Test 15: Script execution fails → GATE_INFRA, action: escalate
  it('script execution failure escalates, not reengages', async () => {
    const exec = vi.fn().mockRejectedValue(new Error('ENOENT: command not found'))
    await expect(assertCodeReviewClean(PR, exec, scriptPath)).rejects.toMatchObject({
      payload: { code: 'GATE_INFRA', action: 'escalate' }
    })
  })

  it('non-JSON script output escalates', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: 'not json' })
    await expect(assertCodeReviewClean(PR, exec, scriptPath)).rejects.toMatchObject({
      payload: { code: 'GATE_INFRA', action: 'escalate' }
    })
  })

  it('script reporting error escalates', async () => {
    const exec = vi.fn().mockResolvedValue({
      stdout: JSON.stringify({ clean: null, error: 'judge timed out' })
    })
    await expect(assertCodeReviewClean(PR, exec, scriptPath)).rejects.toMatchObject({
      payload: { code: 'GATE_INFRA', action: 'escalate' }
    })
  })
})
