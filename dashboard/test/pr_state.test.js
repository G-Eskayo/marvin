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

  // marvin#555 (Gil, 2026-10-21): with each check known, the sentence gives way to the progress bar and drill-down.
  it('waiting on checks with per-check rows: no sentence, the progress view instead; Approve still disabled', () => {
    const runs = [{ name: 'a', status: 'passed', done: true }, { name: 'b', status: 'running', done: false }]
    const s = state({ checks: { state: 'pending', failing: [], pending: ['b'], runs } })
    expect(s).toMatchObject({ kind: 'waiting-checks', headline: 'Waiting for GitHub checks', approve: 'disabled', deny: 'enabled', detail: null, checkProgress: true })
  })

  it('failed checks keep their sentence and also offer the rows (no redesign of the failure state)', () => {
    const runs = [{ name: 'a', status: 'failed', done: true }]
    const f = state({ checks: { state: 'failing', failing: ['a'], pending: [], runs } })
    expect(f).toMatchObject({ kind: 'checks-failed', approve: 'hidden', checkProgress: true })
    expect(f.detail).toMatch(/^a\. It is sent back/)
  })

  it('no rows (older data, or an empty list): the old sentence, and no progress view', () => {
    expect(state({ checks: { state: 'pending', failing: [], pending: ['b'], runs: [] } })).toMatchObject({ checkProgress: false })
    expect(state({ checks: { state: 'pending', failing: [], pending: ['b'], runs: [] } }).detail).toMatch(/b still running/)
    expect(state({}).checkProgress).toBe(false)
  })

  it('marvin#231: an older PR on the same files no longer holds Approve; the merge queue orders them', () => {
    const s = state({ waitingOn: [{ number: 29, shared: ['ContentView.swift'] }] })
    expect(s).toMatchObject({ kind: 'ready', approve: 'enabled' })
  })

  it('marvin#231: a queued PR says it is in the merge queue, offers no second Approve, and keeps Deny', () => {
    const q = state({ mergeQueue: { queued: true, state: 'waiting', reason: "waits for #936 (it's built on it)" } })
    expect(q).toMatchObject({ kind: 'in-queue', tone: 'working', headline: 'Approved: in the merge queue', approve: 'hidden', deny: 'enabled' })
    expect(state({ mergeQueue: { queued: true, state: 'queued', reason: 'queued · 2nd · starts after #971' } }).kind).toBe('in-queue')
    expect(state({ mergeQueue: { queued: true, state: 'running', reason: 'merging now' } })).toMatchObject({ kind: 'merging', approve: 'hidden', deny: 'hidden' })
    // Not approved: the line is only a line; the card's own state is unchanged.
    expect(state({ mergeQueue: { queued: false, state: 'waiting', reason: "your answers aren't built yet" } }).kind).toBe('ready')
  })

  it('a queued PR that was sent back meanwhile says sent back, not queued', () => {
    expect(state({ sentBack: true, mergeQueue: { queued: true, state: 'waiting', reason: 'sent back for rework' } }).kind).toBe('sent-back')
  })

  it('a wrong base with no open parent PR is blocked and says what to do', () => {
    const s = state({ baseProblem: { base: 'feature/a', expected: 'main', parent: null } })
    expect(s).toMatchObject({ kind: 'wrong-base', approve: 'hidden' })
    expect(s.detail).toMatch(/Change its base to main/)
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
    expect(r).toEqual({ cleared: true, ticket: 27 }) // the ticket, so the card can drop the label at once (local-first)
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

// #225: what the post-merge rebase found shows on the card before anyone presses Approve.
describe('describePrState: post-merge rebase', () => {
  const ready = { checks: { state: 'passing', failing: [], pending: [] }, waitingOn: [] }

  it('a PR rebased clean says so on the ready card', () => {
    const v = describePrState({ ...ready, rebase: { state: 'clean', after: 229, files: [] } })
    expect(v.kind).toBe('ready')
    expect(v.note).toBe('GitHub checks passed · still merges cleanly onto main after #229 merged')
  })

  it('a conflict names the files and the merge that caused it', () => {
    const v = describePrState({ ...ready, conflicts: true, rebase: { state: 'conflict', after: 229, files: ['a.js', 'b.js'] } })
    expect(v.kind).toBe('conflict')
    expect(v.detail).toContain('Since #229 merged it conflicts in a.js, b.js.')
  })

  it('tests failing after the rebase are shown, and Approve stays available', () => {
    const v = describePrState({ ...ready, rebase: { state: 'tests_failed', after: 229, files: [] } })
    expect(v).toMatchObject({ kind: 'tests-after-rebase', tone: 'wait', approve: 'enabled', headline: 'Tests fail on the latest main' })
    expect(v.detail).toContain('#229')
  })

  it('a PR stacked on an open parent is waiting, not an error, and can be approved: the queue merges its parent first (marvin#231)', () => {
    const s = state({ baseProblem: { base: 'ticket/215-parent', expected: 'main', parent: { number: 307, title: 'North stars single source' } } })
    expect(s).toMatchObject({ kind: 'stacked', tone: 'wait', approve: 'enabled' })
    expect(s.headline).toContain('#307 North stars single source')
    expect(s.detail).toMatch(/Approving queues it: it merges after #307/)
  })
})

describe('describePrState: a PR whose ticket is already closed (#326)', () => {
  it('says it is probably superseded and offers no Approve', () => {
    const v = describePrState({ ...ready, ticketClosed: true, ticketRef: 318 })
    expect(v.kind).toBe('ticket-closed')
    expect(v.headline).toMatch(/ticket is already closed/i)
    expect(v.detail).toMatch(/#318/)
    expect(v.approve).toBe('hidden')
  })

  it('the conflict message says the repair comes first', () => {
    const v = describePrState({ ...ready, conflicts: true })
    expect(v.detail).toMatch(/tries to resolve it automatically/)
  })
})

describe('describePrState: auto-merge shadow verdict (#341)', () => {
  it('says what auto-merge would do on a ready card', () => {
    const would = describePrState({ ...ready, autoMerge: { verdict: 'auto', reasons: [], score: 91 } })
    expect(would.note).toMatch(/Auto-merge \(shadow\): would merge \(tests caught 91% of planted bugs\)/)
    const wait = describePrState({ ...ready, autoMerge: { verdict: 'ask', reasons: ['bin/gh is core (always waits for Gil)'], score: null } })
    expect(wait.note).toMatch(/would wait for you: bin\/gh is core/)
  })
  it('no verdict yet says nothing', () => {
    expect(describePrState({ ...ready }).note || '').not.toMatch(/Auto-merge/)
  })
})

// The owner's answer on #767 (drafts): Approve is hidden on a draft until it's marked ready for review.
describe('describePrState: drafts (marvin#848)', () => {
  it('an otherwise ready draft says it is a draft and offers no Approve; Deny stays', () => {
    const s = state({ isDraft: true })
    expect(s).toMatchObject({ kind: 'draft', approve: 'hidden', deny: 'enabled' })
    expect(s.headline).toMatch(/draft/i)
    expect(s.detail).toMatch(/ready for review/)
  })
  it('a draft waiting on checks or decisions keeps its own story but still no Approve', () => {
    expect(state({ isDraft: true, checks: { state: 'pending', failing: [], pending: ['test'] } })).toMatchObject({ kind: 'waiting-checks', approve: 'hidden' })
    expect(state({ isDraft: true, decisions: { pending: ['names'], problems: [] } })).toMatchObject({ kind: 'decisions-pending', approve: 'hidden', deny: 'enabled' })
    expect(state({ isDraft: true }, { status: 'interrupted' })).toMatchObject({ approve: 'hidden' })
  })
  it('a merge already under way on a draft is shown as it is', () => {
    expect(state({ isDraft: true }, { status: 'approving' }).kind).toBe('merging')
    expect(state({ isDraft: true }, { status: 'queued' }).kind).toBe('queued')
  })
  it('a PR that is not a draft is unchanged', () => {
    expect(state({ isDraft: false })).toMatchObject({ kind: 'ready', approve: 'enabled' })
  })
})

describe('describePrState: image refusals (marvin#807, marvin#743)', () => {
  it('IMAGES_STALE rejection shows the stale images state', () => {
    const s = state({}, { status: 'error', errorMessage: 'IMAGES_STALE at webhook: images are older than the latest commit' })
    expect(s).toMatchObject({ kind: 'images-stale', tone: 'blocked', headline: 'Images are older than the latest change', approve: 'hidden', deny: 'enabled' })
    expect(s.detail).toMatch(/older than the latest/)
  })

  it('IMAGES_STALE is not mirrored: once the images are updated, the card can be approved without an explicit state change', () => {
    // Before pinning: webhook error blocks the PR (status='error', errorMessage is the gate's rejection)
    const blocked = state({}, { status: 'error', errorMessage: 'IMAGES_STALE at webhook: images are older than commit abc123' })
    expect(blocked.kind).toBe('images-stale')
    expect(blocked.approve).toBe('hidden')

    // After the user pins/updates images, the PR body changes (triggering a webhook recheck)
    // The webhook runs again on the same commit and clears the error (no state change, just error gone)
    // This is the non-mirroring behavior: the error was checked server-side, not reproduced client-side
    const cleared = state({}, { status: 'idle', errorMessage: null })
    expect(cleared.kind).toBe('ready')

    // Even if errorMessage was still present from the old webhook run, idle + anything = ready
    // (idle never reads errorMessage), proving the error doesn't persist client-side
    expect(state({}, { status: 'idle', errorMessage: 'IMAGES_STALE at webhook: ...' }).kind).toBe('ready')
  })

  it('NO_UI_EVIDENCE rejection shows the needs-images state', () => {
    const s = state({}, { status: 'error', errorMessage: 'NO_UI_EVIDENCE at webhook: no UI evidence provided' })
    expect(s).toMatchObject({ kind: 'needs-images', tone: 'blocked', headline: 'Needs images', approve: 'hidden', deny: 'enabled' })
  })

  it('IMAGES_UNPINNED rejection shows the needs-images state', () => {
    const s = state({}, { status: 'error', errorMessage: 'IMAGES_UNPINNED at webhook: images not pinned to commits' })
    expect(s).toMatchObject({ kind: 'needs-images', tone: 'blocked', headline: 'Needs images', approve: 'hidden', deny: 'enabled' })
  })

  it('image evidence refusals are not mirrored: once images are pinned/added, the card can be approved', () => {
    // Before pinning: webhook error blocks the PR
    const s = state({}, { status: 'error', errorMessage: 'NO_UI_EVIDENCE at webhook: x' })
    expect(s.kind).toBe('needs-images')
    // Approve is hidden; the user waits for the webhook to recheck once images are pinned/added
    expect(s.approve).toBe('hidden')
    // Once pinning happens and the PR body changes, the next webhook run clears the error
    expect(state({}, { status: 'idle' }).kind).toBe('ready')
  })

  it('image refusals take precedence over generic errors', () => {
    // Image refusal alone → blocked by the image error
    const stale = state({}, { status: 'error', errorMessage: 'IMAGES_STALE at webhook: ...' })
    expect(stale.kind).toBe('images-stale')
    expect(stale.detail).toBeDefined()

    const evidence = state({}, { status: 'error', errorMessage: 'NO_UI_EVIDENCE at webhook: ...' })
    expect(evidence.kind).toBe('needs-images')
  })

  it('but real blockers still win over image refusals (image errors are inserted late in the cascade)', () => {
    // A real conflict beats an image refusal: the PR has both, but conflict is the message shown
    const conflictWins = state({ conflicts: true }, { status: 'error', errorMessage: 'IMAGES_STALE at webhook: ...' })
    expect(conflictWins.kind).toBe('conflict')
    expect(conflictWins.kind).not.toBe('images-stale')

    // Similarly, failing checks beat an image refusal
    const checksWin = state({ checks: { state: 'failing', failing: ['Unit tests'], pending: [] } }, { status: 'error', errorMessage: 'IMAGES_STALE at webhook: ...' })
    expect(checksWin.kind).toBe('checks-failed')
    expect(checksWin.kind).not.toBe('images-stale')

    // Evidence refusal also loses to a real blocker
    const conflictBeatsEvidence = state({ conflicts: true }, { status: 'error', errorMessage: 'NO_UI_EVIDENCE at webhook: ...' })
    expect(conflictBeatsEvidence.kind).toBe('conflict')
  })

  it('a stale image refusal carries the error message as detail', () => {
    const msg = 'IMAGES_STALE at webhook: commit abc123 has newer changes than the screenshot'
    const s = state({}, { status: 'error', errorMessage: msg })
    expect(s.detail).toBe(msg)
  })

  it('stale image refusals hide Approve; the webhook will clear the error automatically once re-pinned', () => {
    const msg = 'IMAGES_STALE at webhook: latest commit is abc123 but screenshot is from xyz789'
    const s = state({}, { status: 'error', errorMessage: msg })
    expect(s.kind).toBe('images-stale')
    expect(s.approve).toBe('hidden') // waiting for webhook recheck after re-pinning; no need to click Approve
    expect(s.deny).toBe('enabled')
  })

  it('an image evidence refusal carries the error message as detail', () => {
    const msg = 'IMAGES_UNPINNED at webhook: screenshot not linked to commit'
    const s = state({}, { status: 'error', errorMessage: msg })
    expect(s.detail).toBe(msg)
  })

  it('the needs-images state from a webhook error is distinct from the card\'s own pr.needsImages check', () => {
    // The card's own check (pr.needsImages) still works independently: says to add/pin images
    const cardOwn = state({ needsImages: { files: ['App.tsx'], unpinned: [] } })
    expect(cardOwn.kind).toBe('needs-images')
    expect(cardOwn.detail).toMatch(/changes how the app looks/)
    expect(cardOwn.detail).not.toMatch(/NO_UI_EVIDENCE/) // not the webhook message

    // A webhook error also shows needs-images, but with the webhook's message, not the card's default
    const webhookMsg = 'NO_UI_EVIDENCE at webhook: no UI evidence provided for the changed screens'
    const webhookError = state({}, { status: 'error', errorMessage: webhookMsg })
    expect(webhookError.kind).toBe('needs-images')
    expect(webhookError.detail).toBe(webhookMsg) // carries the webhook's error message, not the card's pattern
    expect(webhookError.detail).not.toMatch(/changes how the app looks/) // not the card's detail
  })
})
