import { describe, it, expect, vi } from 'vitest'
import {
  hasEvidenceSchema,
  parseEvidence,
  parseTicketRef,
  fetchTicketContext,
  listPipelinePrs,
  approveMr,
  denyMr
} from '../electron/main/mr_review.js'

const PIPELINE_BODY = `Closes G-Eskayo/marvin#42

## Metrics Comparison

**Subsystem**: route.py
**Verdict**: improved

| Metric | Baseline | Current | Delta | Direction |
|---|---|---|---|---|
| accuracy | 0.72 | 0.81 | +0.09 | up |
| cost_usd | 0.045 | 0.038 | -0.007 | down |

## Test Results

**Suite**: pytest
**Passed**: 12
**Failed**: 0
**Total**: 12

## Dev Environment Evidence

N/A — no UI`

const MANUAL_SCHEMA_BODY = `Closes #75

Built manually in a live session, but following the standard evidence format.

## Metrics Comparison

**Subsystem**: dashboard
**Verdict**: n/a

## Test Results

**Suite**: vitest
**Passed**: 8
**Failed**: 0
**Total**: 8

## Dev Environment Evidence

![Screenshot](docs/evidence/pr-75.png)

MR Review tab showing the widened evidence parsing live.`

const NON_SCHEMA_BODY = 'Closes #70\n\nBuilt manually, old-style, no schema sections.'

describe('hasEvidenceSchema', () => {
  it('recognizes a pipeline-raised PR that follows the schema', () => {
    expect(hasEvidenceSchema(PIPELINE_BODY)).toBe(true)
  })

  it('recognizes a manually-raised PR that follows the schema', () => {
    expect(hasEvidenceSchema(MANUAL_SCHEMA_BODY)).toBe(true)
  })

  it('rejects a PR with none of the schema sections', () => {
    expect(hasEvidenceSchema(NON_SCHEMA_BODY)).toBe(false)
  })

  it('rejects a PR missing even one required section', () => {
    const partial = PIPELINE_BODY.replace('## Dev Environment Evidence\n\nN/A — no UI', '')
    expect(hasEvidenceSchema(partial)).toBe(false)
  })

  it('rejects a non-string body without throwing', () => {
    expect(hasEvidenceSchema(null)).toBe(false)
    expect(hasEvidenceSchema(undefined)).toBe(false)
  })
})

describe('parseEvidence', () => {
  it('extracts metrics comparison the same as before (subsystem, verdict, rows)', () => {
    const evidence = parseEvidence(PIPELINE_BODY)
    expect(evidence.subsystem).toBe('route.py')
    expect(evidence.verdict).toBe('improved')
    expect(evidence.metrics).toEqual([
      { name: 'accuracy', baseline: '0.72', current: '0.81', delta: '+0.09', direction: 'up' },
      { name: 'cost_usd', baseline: '0.045', current: '0.038', delta: '-0.007', direction: 'down' }
    ])
  })

  it('extracts test results', () => {
    const evidence = parseEvidence(PIPELINE_BODY)
    expect(evidence.testResults).toEqual({ suite: 'pytest', passed: 12, failed: 0, total: 12 })
  })

  it('extracts an N/A dev-environment-evidence section for a headless change', () => {
    const evidence = parseEvidence(PIPELINE_BODY)
    expect(evidence.devEvidence).toEqual({ na: true, reason: 'no UI' })
  })

  it('extracts a screenshot reference and description for a UI-touching change', () => {
    const evidence = parseEvidence(MANUAL_SCHEMA_BODY)
    expect(evidence.devEvidence).toEqual({
      na: false,
      screenshot: 'docs/evidence/pr-75.png',
      description: 'MR Review tab showing the widened evidence parsing live.'
    })
  })

  it('extracts the linked ticket reference', () => {
    expect(parseEvidence(PIPELINE_BODY).ticketRef).toBe('42')
    expect(parseEvidence(MANUAL_SCHEMA_BODY).ticketRef).toBe('75')
  })

  it('returns nulls for missing evidence sections rather than throwing, independent of ticketRef', () => {
    const evidence = parseEvidence(NON_SCHEMA_BODY)
    expect(evidence).toEqual({
      subsystem: null,
      verdict: null,
      metrics: [],
      testResults: null,
      devEvidence: null,
      ticketRef: '70' // ticketRef parses from anywhere in the body, independent of the schema sections
    })
  })
})

describe('parseTicketRef', () => {
  it('matches a bare "Closes #N"', () => {
    expect(parseTicketRef('Closes #11')).toBe('11')
  })

  it('matches an "owner/repo#N" form', () => {
    expect(parseTicketRef('Fixes G-Eskayo/marvin#42')).toBe('42')
  })

  it('returns null when there is no closing reference', () => {
    expect(parseTicketRef('No ticket reference here.')).toBe(null)
  })
})

describe('listPipelinePrs', () => {
  it('includes both pipeline-raised and manually-raised schema-conforming PRs', async () => {
    const listOpenPrs = vi.fn().mockResolvedValue([
      { number: 70, title: 'Old-style manual PR', url: 'https://x/70', body: NON_SCHEMA_BODY },
      { number: 42, title: 'Pipeline PR', url: 'https://x/42', body: PIPELINE_BODY },
      { number: 75, title: 'Manual, schema-conforming PR', url: 'https://x/75', body: MANUAL_SCHEMA_BODY }
    ])
    const result = await listPipelinePrs(listOpenPrs)
    expect(result.map((pr) => pr.number).sort()).toEqual([42, 75])
  })

  it('attaches parsed evidence and a numeric ticketNumber to each included PR', async () => {
    const listOpenPrs = vi.fn().mockResolvedValue([
      { number: 42, title: 'Pipeline PR', url: 'https://x/42', body: PIPELINE_BODY }
    ])
    const result = await listPipelinePrs(listOpenPrs)
    expect(result[0].evidence.subsystem).toBe('route.py')
    expect(result[0].evidence.testResults.passed).toBe(12)
    expect(result[0].ticketNumber).toBe(42)
  })

  it('sets ticketNumber to null when there is no ticket reference', async () => {
    const noRefBody = PIPELINE_BODY.replace('Closes G-Eskayo/marvin#42\n\n', '')
    const listOpenPrs = vi.fn().mockResolvedValue([
      { number: 42, title: 'Pipeline PR', url: 'https://x/42', body: noRefBody }
    ])
    const result = await listPipelinePrs(listOpenPrs)
    expect(result[0].ticketNumber).toBe(null)
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

describe('denyMr', () => {
  it('posts the deny action, ticket number, reasons, and comment to the webhook', async () => {
    const post = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    await denyMr(
      {
        prUrl: 'https://x/71',
        ticketNumber: 42,
        action: 'send_feedback',
        reasons: ['Insufficient tests'],
        comment: 'needs more coverage'
      },
      'http://localhost:7878/deny',
      post
    )
    expect(post).toHaveBeenCalledWith('http://localhost:7878/deny', {
      action: 'send_feedback',
      pr_url: 'https://x/71',
      ticket_number: 42,
      reasons: ['Insufficient tests'],
      comment: 'needs more coverage'
    })
  })

  it('throws when the webhook call fails, so the UI can surface it', async () => {
    const post = vi.fn().mockResolvedValue({ ok: false, status: 500 })
    await expect(
      denyMr(
        { prUrl: 'https://x/71', ticketNumber: 42, action: 'drop', reasons: [], comment: '' },
        'http://localhost:7878/deny',
        post
      )
    ).rejects.toThrow('Webhook call failed: 500')
  })
})

describe('fetchTicketContext', () => {
  const TICKET_WITH_PARENT_BODY = '## Parent\n\nG-Eskayo/marvin#72\n\n## What to build\n\nDo the thing.'
  const TICKET_NO_PARENT_BODY = '## What to build\n\nDo the thing, no parent.'

  it('fetches the ticket body when there is no parent reference', async () => {
    const ghIssueView = vi.fn().mockResolvedValue({ number: 78, title: 'Ticket', body: TICKET_NO_PARENT_BODY })
    const result = await fetchTicketContext('78', ghIssueView)
    expect(ghIssueView).toHaveBeenCalledWith('78')
    expect(ghIssueView).toHaveBeenCalledTimes(1)
    expect(result.ticket.body).toBe(TICKET_NO_PARENT_BODY)
    expect(result.parent).toBe(null)
  })

  it('also fetches the parent when the ticket declares "## Parent"', async () => {
    const ghIssueView = vi.fn((ref) =>
      ref === '78'
        ? Promise.resolve({ number: 78, title: 'Ticket', body: TICKET_WITH_PARENT_BODY })
        : Promise.resolve({ number: 72, title: 'PRD', body: '## Problem Statement\n\nThe problem.' })
    )
    const result = await fetchTicketContext('78', ghIssueView)
    expect(ghIssueView).toHaveBeenCalledWith('78')
    expect(ghIssueView).toHaveBeenCalledWith('72')
    expect(result.ticket.number).toBe(78)
    expect(result.parent.number).toBe(72)
    expect(result.parent.body).toContain('Problem Statement')
  })

  it('returns null ticket and parent, without throwing, when the ticket fetch fails', async () => {
    const ghIssueView = vi.fn().mockRejectedValue(new Error('gh: issue not found'))
    const result = await fetchTicketContext('999', ghIssueView)
    expect(result).toEqual({ ticket: null, parent: null })
  })

  it('returns a null parent, without throwing, when the parent fetch fails', async () => {
    const ghIssueView = vi.fn((ref) =>
      ref === '78'
        ? Promise.resolve({ number: 78, title: 'Ticket', body: TICKET_WITH_PARENT_BODY })
        : Promise.reject(new Error('gh: parent issue deleted'))
    )
    const result = await fetchTicketContext('78', ghIssueView)
    expect(result.ticket.number).toBe(78)
    expect(result.parent).toBe(null)
  })

  it('returns a null ticket and parent when ghIssueView resolves to a falsy value', async () => {
    const ghIssueView = vi.fn().mockResolvedValue(null)
    const result = await fetchTicketContext('78', ghIssueView)
    expect(result).toEqual({ ticket: null, parent: null })
  })
})
