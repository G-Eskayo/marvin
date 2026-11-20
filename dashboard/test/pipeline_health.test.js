import { describe, it, expect } from 'vitest'
import { classifyPipelineHealth, PIPELINE_AMBER_THRESHOLD_MS } from '../src/lib/pipeline_health.js'

describe('classifyPipelineHealth', () => {
  it('returns null when items is not an array', () => {
    expect(classifyPipelineHealth(null)).toBe(null)
    expect(classifyPipelineHealth(undefined)).toBe(null)
    expect(classifyPipelineHealth({})).toBe(null)
  })

  it('returns null when ticket-pipeline job is not found', () => {
    const items = [
      { job: 'main-health', startedAt: Date.now() },
      { job: 'other-job', startedAt: Date.now() }
    ]
    expect(classifyPipelineHealth(items)).toBe(null)
  })

  it('returns null when pipeline has no startedAt', () => {
    const items = [{ job: 'ticket-pipeline' }]
    expect(classifyPipelineHealth(items)).toBe(null)
  })

  it('returns null when pipeline has not been running long enough for amber', () => {
    const now = Date.now()
    const startedAt = now - 2 * 60 * 1000 // 2 minutes ago
    const items = [{ job: 'ticket-pipeline', startedAt }]
    expect(classifyPipelineHealth(items, now)).toBe(null)
  })

  it('returns amber status when pipeline has been running over threshold', () => {
    const now = Date.now()
    const startedAt = now - 20 * 60 * 1000 // 20 minutes ago
    const items = [{ job: 'ticket-pipeline', startedAt, current: { step: 'Conflicted PRs', detail: 'processing' } }]
    const result = classifyPipelineHealth(items, now)
    expect(result).not.toBe(null)
    expect(result.amber).toBe(true)
    expect(result.step).toBe('Conflicted PRs')
    expect(result.detail).toBe('processing')
  })

  it('handles missing current step/detail', () => {
    const now = Date.now()
    const startedAt = now - 20 * 60 * 1000
    const items = [{ job: 'ticket-pipeline', startedAt }]
    const result = classifyPipelineHealth(items, now)
    expect(result.step).toBe('unknown')
    expect(result.detail).toBe('')
  })

  it('differentiates between pipeline and other jobs', () => {
    const now = Date.now()
    const startedAt = now - 20 * 60 * 1000
    const items = [
      { job: 'main-health', startedAt, current: { step: 'Health check' } },
      { job: 'ticket-pipeline', startedAt, current: { step: 'Conflicted PRs' } }
    ]
    const result = classifyPipelineHealth(items, now)
    expect(result.step).toBe('Conflicted PRs')
  })

  it('includes elapsed time in result', () => {
    const now = Date.now()
    const startedAt = now - 20 * 60 * 1000
    const items = [{ job: 'ticket-pipeline', startedAt, current: { step: 'Processing' } }]
    const result = classifyPipelineHealth(items, now)
    expect(result.elapsed).toBeGreaterThanOrEqual(20 * 60 * 1000)
  })
})
