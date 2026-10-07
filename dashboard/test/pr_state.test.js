import { describe, it, expect } from 'vitest'
import { describePrState } from '../src/lib/prState.js'

const ready = { sentBack: false, conflicts: false, checks: { state: 'passing', failing: [], pending: [] }, waitingOn: [], baseProblem: null }
const state = (over = {}, ui = {}) => describePrState({ ...ready, ...over }, { status: 'idle', errorMessage: null, ...ui })

describe('describePrState: one headline, only the buttons that make sense', () => {
  it('a clean PR is ready: approve and deny both available', () => {
    const s = state()
    expect(s).toMatchObject({ kind: 'ready', approve: 'enabled', deny: 'enabled' })
    expect(s.note).toBe('GitHub checks passed')
  })

  it('merging says so, and hides the buttons you cannot use mid-merge', () => {
    expect(state({}, { status: 'approving' })).toMatchObject({ kind: 'merging', approve: 'hidden', deny: 'hidden' })
  })

  it('SENT BACK wins over everything else, so "nothing to approve" is never next to "approve once checks finish"', () => {
    const s = state({ sentBack: true, checks: { state: 'pending', failing: [], pending: ['App builds'] }, conflicts: true })
    expect(s.kind).toBe('sent-back')
    expect(s.approve).toBe('hidden')
    expect(s.detail).toMatch(/nothing to approve/i)
    expect(s.detail).not.toMatch(/approve once|checks finish|still running/i)
    expect(s.actions.map((a) => a.id)).toContain('clearSentBack') // the way out when the label is wrong
  })

  it('a refusal left over from an earlier click is never shown on top of the state that caused it', () => {
    const s = state({ sentBack: true }, { status: 'error', errorMessage: 'SENT_BACK at request: this PR was sent back' })
    expect(s.kind).toBe('sent-back')
    expect(JSON.stringify(s)).not.toMatch(/Failed|SENT_BACK at request/)
  })

  it('and once that state clears, the stale refusal does not come back', () => {
    for (const code of ['SENT_BACK', 'CI_PENDING', 'CI_FAILED', 'WRONG_BASE']) {
      expect(state({}, { status: 'error', errorMessage: `${code} at request: x` }).kind).toBe('ready')
    }
  })

  it('a real merge failure is shown, and the PR can be tried again', () => {
    const s = state({}, { status: 'error', errorMessage: 'MERGE_REFUSED at merging: GitHub refused it' })
    expect(s).toMatchObject({ kind: 'error', approve: 'enabled' })
    expect(s.detail).toMatch(/GitHub refused it/)
  })

  it('conflicts and failing checks are sent back automatically: no approve button, nothing to do', () => {
    expect(state({ conflicts: true })).toMatchObject({ kind: 'conflict', approve: 'hidden' })
    const f = state({ checks: { state: 'failing', failing: ['CaptionCore unit tests'], pending: [] } })
    expect(f).toMatchObject({ kind: 'checks-failed', approve: 'hidden' })
    expect(f.detail).toMatch(/CaptionCore unit tests/)
  })

  it('waiting on checks is shown as waiting: approve is visible but disabled, and says what it is waiting for', () => {
    const s = state({ checks: { state: 'pending', failing: [], pending: ['App builds (iOS Simulator)'] } })
    expect(s).toMatchObject({ kind: 'waiting-checks', approve: 'disabled', deny: 'enabled' })
    expect(s.detail).toMatch(/App builds/)
  })

  it('waiting on an older PR names it', () => {
    const s = state({ waitingOn: [{ number: 29, shared: ['ContentView.swift'] }] })
    expect(s).toMatchObject({ kind: 'waiting-order', approve: 'disabled' })
    expect(s.headline).toMatch(/#29/)
  })

  it('a wrong base is explained with what to do', () => {
    const s = state({ baseProblem: { base: 'feature/a', expected: 'main', parent: { number: 7 } } })
    expect(s).toMatchObject({ kind: 'wrong-base', approve: 'hidden' })
    expect(s.detail).toMatch(/#7/)
  })

  it('a GitHub outage says so, keeps Approve available, and does not blame the PR', () => {
    const s = state({}, { status: 'error', errorMessage: 'GITHUB_OUTAGE at merging: remote: Internal Server Error' })
    expect(s).toMatchObject({ kind: 'github-outage', approve: 'enabled', deny: 'enabled' })
    expect(s.headline).toMatch(/GitHub is having an outage/)
    expect(s.detail).toMatch(/nothing is wrong with this PR/i)
  })

  it('a previous "sent back for rework" result is shown once, as the PR\'s state, not as an error', () => {
    const s = state({}, { status: 'reengaged', errorMessage: 'REBASE_CONFLICT: ...' })
    expect(s.kind).toBe('sent-back-now')
    expect(s.approve).toBe('hidden')
  })
})

import { clearSentBackLabel } from '../electron/main/mr_review.js'
describe('clearSentBackLabel: the way out when the label is wrong', () => {
  const URL = 'https://github.com/G-Eskayo/clarity-captions/pull/66'
  const world = (labels) => {
    const calls = []
    const exec = async (cmd, args) => {
      calls.push(args)
      if (args[0] === 'pr' && args.includes('body')) return { stdout: JSON.stringify({ body: 'Closes G-Eskayo/clarity-captions#27\n\nstuff' }) }
      if (args[0] === 'issue' && args[1] === 'view') return { stdout: JSON.stringify({ labels: labels.map((name) => ({ name })) }) }
      return { stdout: '' }
    }
    return { exec, calls }
  }

  it('removes the label from the PR\'s own ticket and leaves a comment saying who did it and why', async () => {
    const w = world(['ready-for-agent', 'needs-reengagement'])
    const r = await clearSentBackLabel(URL, w.exec)
    expect(r).toEqual({ cleared: true })
    const edit = w.calls.find((a) => a[1] === 'edit')
    expect(edit).toEqual(expect.arrayContaining(['27', '--repo', 'G-Eskayo/clarity-captions', '--remove-label', 'needs-reengagement']))
    expect(w.calls.some((a) => a[1] === 'comment')).toBe(true)
  })

  it('refuses while a rework is actually running (the ticket is claimed): clearing it would race the rebuild', async () => {
    const w = world(['needs-reengagement', 'claimed:mac-mini'])
    const r = await clearSentBackLabel(URL, w.exec)
    expect(r.cleared).toBe(false)
    expect(r.reason).toMatch(/rework is running|claimed by mac-mini/i)
    expect(w.calls.some((a) => a[1] === 'edit')).toBe(false)
  })

  it('says so when the ticket is not sent back at all', async () => {
    const r = await clearSentBackLabel(URL, world(['ready-for-agent']).exec)
    expect(r).toMatchObject({ cleared: false, reason: expect.stringMatching(/not sent back/i) })
  })

  it('says so when the PR has no ticket', async () => {
    const exec = async () => ({ stdout: JSON.stringify({ body: 'hand-made PR' }) })
    expect(await clearSentBackLabel(URL, exec)).toMatchObject({ cleared: false, reason: expect.stringMatching(/no ticket/i) })
  })
})

import { listPipelinePrs } from '../electron/main/mr_review.js'
describe('a sent-back PR says where its rework stands', () => {
  const basePr = { number: 172, title: 'Implement #143', url: 'u', repo: 'G-Eskayo/marvin', body: 'Closes G-Eskayo/marvin#143', files: [] }
  const status = { state: 'queued', headline: 'Queued: 6th of 9 waiting', detail: 'Nothing is running right now.', position: 6, of: 9 }

  it('the list attaches the status of the PR\'s own ticket, only for sent-back tickets', async () => {
    const list = await listPipelinePrs(async () => [basePr, { ...basePr, number: 5, body: 'Closes G-Eskayo/marvin#9' }], {
      sentBackTickets: async () => new Set(['G-Eskayo/marvin#143']),
      reworkStatus: async () => ({ 'G-Eskayo/marvin#143': status })
    })
    expect(list[0].rework).toEqual(status)
    expect(list[1].rework).toBeNull()
  })

  it('a failing status lookup never hides or breaks the PR', async () => {
    const list = await listPipelinePrs(async () => [basePr], {
      sentBackTickets: async () => new Set(['G-Eskayo/marvin#143']),
      reworkStatus: async () => { throw new Error('boom') }
    })
    expect(list[0].sentBack).toBe(true)
    expect(list[0].rework).toBeNull()
  })

  it('the card shows the status next to "sent back", whatever it is', () => {
    const s = describePrState({ ...ready, sentBack: true, rework: status }, { status: 'idle', errorMessage: null })
    expect(s.kind).toBe('sent-back')
    expect(s.rework).toEqual(status)
  })

  it('without a status it still says it is sent back, and admits it does not know where the rework is', () => {
    const s = describePrState({ ...ready, sentBack: true }, { status: 'idle', errorMessage: null })
    expect(s.rework).toBeNull()
    expect(s.detail).toMatch(/nothing to approve/i)
  })
})

import { getReworkStatus, clearReworkCache } from '../electron/main/rework.js'
describe('getReworkStatus', () => {
  it('caches for a minute, and a failing report means no status rather than an error', async () => {
    clearReworkCache()
    let calls = 0
    const run = async () => { calls++; return '{"o/r#1":{"state":"queued"}}' }
    expect(await getReworkStatus({ run, now: 1000 })).toEqual({ 'o/r#1': { state: 'queued' } })
    await getReworkStatus({ run, now: 30_000 })
    expect(calls).toBe(1)
    clearReworkCache()
    expect(await getReworkStatus({ run: async () => { throw new Error('boom') }, now: 1000 })).toEqual({})
  })
})
