import { describe, it, expect, vi } from 'vitest'

vi.mock('../webhook-server/ticket_stages.js', () => ({ recordStage: vi.fn() }))
vi.mock('../webhook-server/failure_log.js', () => ({ recordFailure: vi.fn() }))
vi.mock('../webhook-server/rebase_status.js', () => ({ writeRebaseStatus: vi.fn(), readRebaseStatus: vi.fn(() => ({})) }))

import { readyIfDraft, mergePr } from '../webhook-server/merge.js'
import { classifyFailure } from '../webhook-server/failure.js'

// clarity-captions #77/#78 (2026-10-09): the owner pressed Approve on draft PRs, the gate ran its full rebase and
// retest, and only then did `gh pr merge` fail with "Pull Request is still a draft", reported as UNKNOWN.
// Only a human's Approve reaches mergePr (dashboard and phone), so that click IS the "ready" decision.
const PR = 'https://github.com/G-Eskayo/clarity-captions/pull/77'

function ghWith({ isDraft, readyFails = false, viewFails = false }) {
  return vi.fn(async (cmd, args) => {
    if (cmd === 'gh' && args[1] === 'view' && args.includes('isDraft')) {
      if (viewFails) throw new Error('boom')
      return { stdout: JSON.stringify({ isDraft }), stderr: '' }
    }
    if (cmd === 'gh' && args[1] === 'ready' && readyFails) {
      throw Object.assign(new Error('Command failed: gh pr ready'), { stderr: 'HTTP 403: Resource not accessible by integration' })
    }
    return { stdout: JSON.stringify({ baseRefName: 'main', isDraft }), stderr: '' }
  })
}

const callsOf = (exec, sub) => exec.mock.calls.filter((c) => c[0] === 'gh' && c[1][1] === sub)

describe('a draft PR approved by the owner is marked ready, not failed', () => {
  it('marks a draft ready and says so on the PR', async () => {
    const exec = ghWith({ isDraft: true })
    await expect(readyIfDraft(PR, exec)).resolves.toBe(true)
    expect(callsOf(exec, 'ready')).toHaveLength(1)
    expect(callsOf(exec, 'ready')[0][1]).toContain(PR)
    const comment = callsOf(exec, 'comment')
    expect(comment).toHaveLength(1)
    expect(comment[0][1].join(' ')).toMatch(/approve/i)
  })

  it('leaves a non-draft PR alone', async () => {
    const exec = ghWith({ isDraft: false })
    await expect(readyIfDraft(PR, exec)).resolves.toBe(false)
    expect(callsOf(exec, 'ready')).toHaveLength(0)
    expect(callsOf(exec, 'comment')).toHaveLength(0)
  })

  it('does not block on a metadata hiccup (the merge would fail loudly, and is now classified)', async () => {
    await expect(readyIfDraft(PR, ghWith({ isDraft: true, viewFails: true }))).resolves.toBe(false)
    await expect(readyIfDraft(PR, vi.fn().mockResolvedValue({ stdout: 'not json' }))).resolves.toBe(false)
  })

  it('refuses with PR_DRAFT, before any gate work, when GitHub will not mark it ready', async () => {
    const exec = ghWith({ isDraft: true, readyFails: true })
    await expect(readyIfDraft(PR, exec)).rejects.toMatchObject({ payload: { code: 'PR_DRAFT', action: 'escalate' } })
  })

  it('mergePr readies the draft BEFORE the gate and the merge, so a draft never costs a full retest', async () => {
    const exec = ghWith({ isDraft: true })
    const shouldGate = vi.fn().mockResolvedValue({ gate: false, body: '' })
    await mergePr('https://github.com/G-Eskayo/marvin/pull/77', exec, () => Promise.resolve(), () => {}, shouldGate)
    const order = exec.mock.calls.filter((c) => c[0] === 'gh').map((c) => c[1][1])
    expect(order.indexOf('ready')).toBeGreaterThanOrEqual(0)
    expect(order.indexOf('ready')).toBeLessThan(order.indexOf('merge'))
    expect(shouldGate.mock.invocationCallOrder[0]).toBeGreaterThan(
      exec.mock.invocationCallOrder[exec.mock.calls.findIndex((c) => c[1][1] === 'ready')])
  })
})

describe('the draft refusal is classified, not UNKNOWN', () => {
  it('names the exact GitHub error as PR_DRAFT', () => {
    const error = Object.assign(new Error('Command failed: gh pr merge'), { stderr: 'GraphQL: Pull Request is still a draft (mergePullRequest)' })
    expect(classifyFailure({ stage: 'merging', error })).toMatchObject({ code: 'PR_DRAFT', action: 'escalate', retryable: false })
  })
})
