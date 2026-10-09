import { describe, it, expect, vi } from 'vitest'
import {
  hasEvidenceSchema,
  parseEvidence,
  parseTicketRef,
  fetchTicketContext,
  listPipelinePrs,
  sentBackKeys,
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

N/A — no UI

## Mutation Score

80% (4/5)`

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
      mutation: null,
      ticketRef: '70' // ticketRef parses from anywhere in the body, independent of the schema sections
    })
  })

  it('extracts mutation score when present', () => {
    const evidence = parseEvidence(PIPELINE_BODY)
    expect(evidence.mutation).toEqual({ status: 'ok', score: 80, killed: 4, total: 5 })
  })

  it('parses unknown mutation status with reason', () => {
    const body = `Closes #42\n## Mutation Score\n\nunknown (npx not found)`
    const evidence = parseEvidence(body)
    expect(evidence.mutation).toEqual({ status: 'unknown', reason: 'npx not found' })
  })

  it('parses no mutable lines mutation status', () => {
    const body = `Closes #42\n## Mutation Score\n\nno mutable lines`
    const evidence = parseEvidence(body)
    expect(evidence.mutation).toEqual({ status: 'ok', score: 100, killed: 0, total: 0, reason: 'no mutable lines' })
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
  it('includes every open PR regardless of schema conformance', async () => {
    // Found live 2026-10-01: PR #119 (real, substantive, its own test-plan
    // checklist) sat invisible for 30 days because it didn't follow the
    // exact evidence-schema template -- true of any manually-authored PR,
    // not just malformed ones. A real PR disappearing with no indication
    // it was excluded is worse than showing it with less structure.
    const listOpenPrs = vi.fn().mockResolvedValue([
      { number: 70, title: 'Old-style manual PR', url: 'https://x/70', body: NON_SCHEMA_BODY },
      { number: 42, title: 'Pipeline PR', url: 'https://x/42', body: PIPELINE_BODY },
      { number: 75, title: 'Manual, schema-conforming PR', url: 'https://x/75', body: MANUAL_SCHEMA_BODY }
    ])
    const result = await listPipelinePrs(listOpenPrs)
    expect(result.map((pr) => pr.number).sort()).toEqual([42, 70, 75])
  })

  it('flags non-conforming PRs with hasSchema: false and the full raw body instead of parsed evidence', async () => {
    const listOpenPrs = vi.fn().mockResolvedValue([
      { number: 70, title: 'Old-style manual PR', url: 'https://x/70', body: NON_SCHEMA_BODY }
    ])
    const result = await listPipelinePrs(listOpenPrs)
    expect(result[0].hasSchema).toBe(false)
    expect(result[0].evidence).toBe(null)
    expect(result[0].ticketNumber).toBe(null)
    expect(result[0].rawBody).toBe(NON_SCHEMA_BODY) // untruncated -- MrDetail needs the whole thing
  })

  it('flags conforming PRs with hasSchema: true and no raw body', async () => {
    const listOpenPrs = vi.fn().mockResolvedValue([
      { number: 42, title: 'Pipeline PR', url: 'https://x/42', body: PIPELINE_BODY }
    ])
    const result = await listPipelinePrs(listOpenPrs)
    expect(result[0].hasSchema).toBe(true)
    expect(result[0].rawBody).toBe(null)
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
    const post = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ merged: true, reengaged: false, reason: null }) })
    await approveMr('https://x/71', 'http://localhost:7878/approve', post)
    expect(post).toHaveBeenCalledWith('http://localhost:7878/approve', { pr_url: 'https://x/71' })
  })

  it('returns the parsed body so callers can tell a merge apart from a re-engagement route', async () => {
    // G-Eskayo/marvin#91's merge-time gate: a 200 can mean either.
    const post = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ merged: false, reengaged: true, reason: 'Tests failed after rebasing onto main' })
    })
    const result = await approveMr('https://x/71', 'http://localhost:7878/approve', post)
    expect(result).toEqual({ merged: false, reengaged: true, reason: 'Tests failed after rebasing onto main' })
  })

  it('throws when the webhook call fails, so the UI can surface it', async () => {
    const post = vi.fn().mockResolvedValue({ ok: false, status: 500 })
    await expect(approveMr('https://x/71', 'http://localhost:7878/approve', post)).rejects.toThrow(
      'Webhook call failed: 500'
    )
  })

  // 2026-10-02: "Webhook call failed: 500" hid the real reason, which cost a long hunt.
  it('surfaces the server\'s structured reason: code, stage, message and what happens next', async () => {
    const post = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ merged: false, code: 'GH_AUTH_INVALID', stage: 'merging', message: 'HTTP 401: Bad credentials',
                           action: 'escalate', remediation: 'Fix ~/.claude/.gh-token on the webhook machine.' })
    })
    const err = await approveMr('https://x/71', 'http://localhost:7878/approve', post).catch((e) => e)
    expect(err.message).toContain('GH_AUTH_INVALID at merging')
    expect(err.message).toContain('Bad credentials')
    expect(err.message).toContain('needs you')
    expect(err.message).toContain('.gh-token')
    expect(err.payload.code).toBe('GH_AUTH_INVALID')
  })

  it('says it already retried for a retry-class failure', async () => {
    const post = vi.fn().mockResolvedValue({
      ok: false, status: 500,
      json: async () => ({ merged: false, code: 'TRANSIENT_NETWORK', stage: 'merging', message: 'ETIMEDOUT', action: 'retry', attempts: 4, remediation: 'Check connectivity.' })
    })
    const err = await approveMr('https://x/71', 'http://localhost:7878/approve', post).catch((e) => e)
    expect(err.message).toContain('retried 4')
  })

  it('falls back to the bare status when the body is not JSON or has no code', async () => {
    const post = vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => { throw new Error('not json') } })
    await expect(approveMr('https://x/71', 'http://localhost:7878/approve', post)).rejects.toThrow('Webhook call failed: 502')
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

describe('listPipelinePrs: sent-back tickets (marvin #129)', () => {
  const CC = 'G-Eskayo/clarity-captions'
  const prs = () => [
    { number: 49, title: 'Reworked localization', url: 'https://github.com/G-Eskayo/clarity-captions/pull/49', repo: CC, body: 'Closes G-Eskayo/clarity-captions#35' },
    { number: 50, title: 'A different ticket', url: 'https://github.com/G-Eskayo/clarity-captions/pull/50', repo: CC, body: 'Closes #36' },
    { number: 7, title: 'marvin PR citing the same number', url: 'https://github.com/G-Eskayo/marvin/pull/7', repo: 'G-Eskayo/marvin', body: 'Closes #35' },
    { number: 8, title: 'Hand-written PR, no ticket', url: 'https://github.com/G-Eskayo/marvin/pull/8', repo: 'G-Eskayo/marvin', body: 'no closing keyword' }
  ]

  it('flags a PR whose ticket is sent back, matching the ticket in the PR\'s own repo only', async () => {
    const result = await listPipelinePrs(async () => prs(), { sentBackTickets: async () => new Set([`${CC}#35`]) })
    expect(result.map((r) => [r.number, r.sentBack])).toEqual([[49, true], [50, false], [7, false], [8, false]])
  })

  it('works for PRs that do not follow the evidence schema (the ticket comes from the closing keyword)', async () => {
    const result = await listPipelinePrs(async () => prs(), { sentBackTickets: async () => new Set([`${CC}#35`]) })
    expect(result[0].hasSchema).toBe(false)
    expect(result[0].sentBack).toBe(true)
  })

  it('asks only about the repositories that actually have PRs, once each', async () => {
    const lookup = vi.fn().mockResolvedValue(new Set())
    await listPipelinePrs(async () => prs(), { sentBackTickets: lookup })
    expect(lookup).toHaveBeenCalledTimes(1)
    expect([...lookup.mock.calls[0][0]].sort()).toEqual([CC, 'G-Eskayo/marvin'])
  })

  it('is false for everything when no lookup is given', async () => {
    const result = await listPipelinePrs(async () => prs())
    expect(result.every((r) => r.sentBack === false)).toBe(true)
  })

  it('a failing lookup never hides a PR or stops the list', async () => {
    const result = await listPipelinePrs(async () => prs(), { sentBackTickets: async () => { throw new Error('gh down') } })
    expect(result).toHaveLength(4)
    expect(result.every((r) => r.sentBack === false)).toBe(true)
  })
})

describe('sentBackKeys', () => {
  const issue = (number, state, labels) => ({ number, state, labels: labels.map((name) => ({ name })) })

  it('collects repo#number for open tickets labelled needs-reengagement', () => {
    const keys = sentBackKeys('G-Eskayo/clarity-captions', [
      issue(35, 'OPEN', ['ready-for-agent', 'needs-reengagement']),
      issue(36, 'OPEN', ['ready-for-agent']),
      issue(37, 'OPEN', [])
    ])
    expect([...keys]).toEqual(['G-Eskayo/clarity-captions#35'])
  })

  it('ignores closed tickets (a stale label on finished work is not "sent back")', () => {
    expect(sentBackKeys('G-Eskayo/marvin', [issue(5, 'CLOSED', ['needs-reengagement'])]).size).toBe(0)
  })

  it('copes with missing fields', () => {
    expect(sentBackKeys('G-Eskayo/marvin', [{ number: 1, state: 'OPEN' }, null, undefined].filter(Boolean)).size).toBe(0)
    expect(sentBackKeys('G-Eskayo/marvin', undefined).size).toBe(0)
  })
})


describe('listPipelinePrs: post-merge rebase result (#225)', () => {
  it("attaches each PR's latest rebase result, and a failing lookup attaches nothing", async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/208'
    const list = async () => [{ number: 208, title: 't', url, body: '' }]
    const [withIt] = await listPipelinePrs(list, { rebaseStatus: async () => ({ [url]: { state: 'conflict', after: 229, files: ['a.js'] } }) })
    expect(withIt.rebase).toEqual({ state: 'conflict', after: 229, files: ['a.js'] })
    const [without] = await listPipelinePrs(list, { rebaseStatus: async () => { throw new Error('webhook down') } })
    expect(without.rebase).toBe(null)
  })
})
