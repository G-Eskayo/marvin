import { describe, it, expect, vi } from 'vitest'
import { recordRefusal, recordApproveError, approveErrorLine } from '../webhook-server/refusal_log.js'
import { recordFailure } from '../webhook-server/failure_log.js'

// #215: every refused or failed merge is recorded with its PR, project, ticket, stage and time.
const NOW = () => new Date('2026-10-07T20:00:00.000Z')
const PR = 'https://github.com/G-Eskayo/marvin/pull/209'
const CLARITY_PR = 'https://github.com/G-Eskayo/clarity-captions/pull/66'

function deps() {
  return { append: vi.fn(), recordStageFn: vi.fn(), now: NOW, file: '/tmp/f.jsonl' }
}
const line = (d) => JSON.parse(d.append.mock.calls[0][1])

describe('recordRefusal', () => {
  it('appends a refusal (not a failure, so the breaker ignores it) with PR, project, ticket and stage', () => {
    const d = deps()
    recordRefusal({ prUrl: PR, ticket: 158, code: 'OUT_OF_ORDER', message: 'Merge #208 first', stage: 'request' }, d)
    expect(line(d)).toEqual({
      t: '2026-10-07T20:00:00.000Z', kind: 'refusal', ticket: 158, project: 'G-Eskayo/marvin', pr_url: PR,
      sig: 'merge:OUT_OF_ORDER', stage: 'request', reason: 'OUT_OF_ORDER: Merge #208 first'
    })
  })

  it("puts the refusal in the ticket's stage log as a failed merging stage, under its own project", () => {
    const d = deps()
    recordRefusal({ prUrl: CLARITY_PR, ticket: 7, code: 'SENT_BACK', message: 'sent back', stage: 'request' }, d)
    expect(d.recordStageFn).toHaveBeenCalledWith(7, 'merging', 'failed', 'refused SENT_BACK: sent back', { repo: 'G-Eskayo/clarity-captions' })
  })

  it('still records a refusal with no linked ticket, but writes no stage log', () => {
    const d = deps()
    recordRefusal({ prUrl: PR, ticket: null, code: 'WRONG_BASE', message: 'targets x', stage: 'request' }, d)
    expect(line(d).ticket).toBe(null)
    expect(d.recordStageFn).not.toHaveBeenCalled()
  })

  it('never throws, even when both writes fail', () => {
    const d = { ...deps(), append: () => { throw new Error('disk full') }, recordStageFn: () => { throw new Error('x') } }
    expect(() => recordRefusal({ prUrl: PR, ticket: 1, code: 'X', message: 'm', stage: 'request' }, d)).not.toThrow()
  })
})

describe('recordApproveError (the webhook /approve error path)', () => {
  const exec = vi.fn(async () => ({ stdout: JSON.stringify({ body: 'Closes G-Eskayo/marvin#158' }) }))

  for (const code of ['WRONG_BASE', 'SENT_BACK', 'CI_PENDING', 'NO_MERGE_PROFILE']) {
    it(`records a ${code} refusal against the PR's ticket, looked up from the PR body`, async () => {
      const d = deps()
      await recordApproveError(PR, { code, stage: 'request', message: 'no' }, { ...d, exec })
      expect(line(d)).toMatchObject({ kind: 'refusal', sig: `merge:${code}`, ticket: 158, pr_url: PR, stage: 'request' })
      expect(d.recordStageFn).toHaveBeenCalledWith(158, 'merging', 'failed', `refused ${code}: no`, { repo: 'G-Eskayo/marvin' })
    })
  }

  it('records MERGE_REFUSED as a refusal without a second stage entry (mergePr already wrote one)', async () => {
    const d = deps()
    await recordApproveError(PR, { code: 'MERGE_REFUSED', stage: 'merging', message: 'later' }, { ...d, exec })
    expect(line(d).kind).toBe('refusal')
    expect(d.recordStageFn).not.toHaveBeenCalled()
  })

  it('leaves real failures alone: mergePr already recorded those', async () => {
    const d = deps()
    await recordApproveError(PR, { code: 'NOT_MERGEABLE', stage: 'merging', message: 'conflict' }, { ...d, exec })
    expect(d.append).not.toHaveBeenCalled()
  })

  it('a failing ticket lookup still records the refusal, without a ticket', async () => {
    const d = deps()
    await recordApproveError(PR, { code: 'WRONG_BASE', stage: 'request', message: 'no' }, { ...d, exec: async () => { throw new Error('gh down') } })
    expect(line(d)).toMatchObject({ kind: 'refusal', ticket: null })
  })
})

describe('approveErrorLine', () => {
  it('starts with an ISO timestamp and carries the PR URL', () => {
    expect(approveErrorLine(PR, { error: 'SENT_BACK at request: no' }, NOW))
      .toBe(`2026-10-07T20:00:00.000Z approve failed: ${PR} SENT_BACK at request: no`)
  })
})

describe('recordFailure carries project, PR and stage when given', () => {
  it('so another project\'s merge failures are not counted against marvin', () => {
    const append = vi.fn()
    recordFailure({ ticket: 7, code: 'NOT_MERGEABLE', message: 'm', project: 'G-Eskayo/clarity-captions', prUrl: CLARITY_PR, stage: 'merging' }, append, NOW, '/tmp/x')
    expect(JSON.parse(append.mock.calls[0][1])).toMatchObject({ kind: 'failure', project: 'G-Eskayo/clarity-captions', pr_url: CLARITY_PR, stage: 'merging' })
  })
})
