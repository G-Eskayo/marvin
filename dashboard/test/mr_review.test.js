import { describe, it, expect, vi } from 'vitest'
import { isPipelinePr, parseMetricsEvidence, listPipelinePrs, approveMr } from '../electron/main/mr_review.js'

const PIPELINE_BODY = `Closes G-Eskayo/marvin#42

Autonomously implemented and verified by the MR pipeline. Metrics comparison (evidence this change is genuinely better, not just different):

**Subsystem**: route.py
**Verdict**: improved

| Metric | Baseline | Current | Delta | Direction |
|---|---|---|---|---|
| accuracy | 0.72 | 0.81 | +0.09 | up |
| cost_usd | 0.045 | 0.038 | -0.007 | down |`

describe('isPipelinePr', () => {
  it('recognizes a real pipeline-raised PR body', () => {
    expect(isPipelinePr(PIPELINE_BODY)).toBe(true)
  })

  it('rejects a manually-written PR body', () => {
    expect(isPipelinePr('Closes #70\n\nBuilt manually in a live session.')).toBe(false)
  })

  it('recognizes a ticket-dispatched PR that closes an issue and has a Test plan section, even without the mr_raiser marker', () => {
    const body = `## Summary\n\nCloses #24. Some real change.\n\n## Test plan\n\n- [x] pytest passed`
    expect(isPipelinePr(body)).toBe(true)
  })

  it('still rejects a PR with only a Test plan section but no issue reference', () => {
    const body = `## Summary\n\nGeneral cleanup, not tied to a ticket.\n\n## Test plan\n\n- [x] pytest passed`
    expect(isPipelinePr(body)).toBe(false)
  })

  it('rejects a non-string body without throwing', () => {
    expect(isPipelinePr(null)).toBe(false)
    expect(isPipelinePr(undefined)).toBe(false)
  })
})

describe('parseMetricsEvidence', () => {
  it('extracts subsystem, verdict, and every metric row', () => {
    const evidence = parseMetricsEvidence(PIPELINE_BODY)
    expect(evidence.subsystem).toBe('route.py')
    expect(evidence.verdict).toBe('improved')
    expect(evidence.metrics).toEqual([
      { name: 'accuracy', baseline: '0.72', current: '0.81', delta: '+0.09', direction: 'up' },
      { name: 'cost_usd', baseline: '0.045', current: '0.038', delta: '-0.007', direction: 'down' }
    ])
  })

  it('returns nulls and an empty metrics list for a body with no table', () => {
    const evidence = parseMetricsEvidence('Closes #1\n\nNo evidence here.')
    expect(evidence).toEqual({ subsystem: null, verdict: null, metrics: [] })
  })
})

describe('listPipelinePrs', () => {
  it('filters to only pipeline-raised PRs and attaches parsed evidence', async () => {
    const listOpenPrs = vi.fn().mockResolvedValue([
      { number: 70, title: 'Manual PR', url: 'https://x/70', body: 'Closes #70\n\nBuilt manually.' },
      { number: 71, title: 'Pipeline PR', url: 'https://x/71', body: PIPELINE_BODY }
    ])
    const result = await listPipelinePrs(listOpenPrs)
    expect(result).toHaveLength(1)
    expect(result[0].number).toBe(71)
    expect(result[0].evidence.subsystem).toBe('route.py')
  })

  it('returns an empty list when there are no open PRs at all', async () => {
    const listOpenPrs = vi.fn().mockResolvedValue([])
    expect(await listPipelinePrs(listOpenPrs)).toEqual([])
  })
})

describe('approveMr', () => {
  it('posts the PR url to the webhook and resolves on success', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    await approveMr('https://x/71', 'http://localhost:7878/approve', post)
    expect(post).toHaveBeenCalledWith('http://localhost:7878/approve', { pr_url: 'https://x/71' })
  })

  it('throws when the webhook call fails, so the UI can surface it', async () => {
    const post = vi.fn().mockResolvedValue({ ok: false, status: 500 })
    await expect(approveMr('https://x/71', 'http://localhost:7878/approve', post)).rejects.toThrow(
      'Webhook call failed: 500'
    )
  })
})
