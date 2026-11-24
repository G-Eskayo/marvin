import { describe, it, expect } from 'vitest'
import { describePrState, queueLineFor } from './prState.js'

describe('prState: conflict handling', () => {
  const basePr = {
    number: 972,
    title: 'Fix a conflict',
    isDraft: false,
    checks: { state: 'passing', failing: [], pending: [] }
  }

  it('a PR in queue waiting on conflict has the right card state', () => {
    const pr = {
      ...basePr,
      mergeQueue: {
        state: 'waiting',
        conflict: true,
        queued: true,
        reason: "Held: conflicts with main after #970 in src/app.js, src/state.js · MARVIN is fixing it",
        waitsFor: null,
        position: 2
      }
    }
    const state = describePrState(pr)
    expect(state.kind).toBe('in-queue-conflict')
    expect(state.tone).toBe('blocked')
    expect(state.headline).toBe('Held in the queue: waiting on a conflict')
    expect(state.approve).toBe('hidden')
    expect(state.deny).toBe('enabled')
  })

  it('queueLineFor shows the line when not already in headline', () => {
    const pr = {
      ...basePr,
      mergeQueue: {
        state: 'waiting',
        conflict: true,
        queued: true,
        reason: "Held: conflicts with main after #970 in src/app.js · MARVIN is fixing it",
        waitsFor: null,
        position: 2
      }
    }
    const line = queueLineFor(pr)
    expect(line).toEqual(pr.mergeQueue)
  })

  it('queueLineFor hides the line when it repeats the headline for in-queue-conflict', () => {
    const pr = {
      ...basePr,
      mergeQueue: {
        state: 'waiting',
        conflict: true,
        queued: true,
        reason: "Held in the queue: waiting on a conflict",
        waitsFor: null,
        position: 2
      }
    }
    const line = queueLineFor(pr)
    expect(line).toBeNull()
  })

  it('a normal queued PR still shows as working state', () => {
    const pr = {
      ...basePr,
      mergeQueue: {
        state: 'queued',
        queued: true,
        reason: 'queued · 1st · starts next',
        position: 1
      }
    }
    const state = describePrState(pr)
    expect(state.kind).toBe('in-queue')
    expect(state.tone).toBe('working')
  })

  it('a queued PR with no state defaults to old behavior', () => {
    const pr = {
      ...basePr,
      mergeQueue: {
        queued: true,
        reason: 'queued · 1st · starts next',
        position: 1
      }
    }
    const state = describePrState(pr)
    expect(state.kind).toBe('in-queue')
  })

  it('a PR in queue waiting on conflict but without pr.conflicts shows in-queue-conflict', () => {
    const pr = {
      ...basePr,
      mergeQueue: {
        state: 'waiting',
        conflict: true,
        queued: true,
        reason: "Held: conflicts with main after #970 · MARVIN is fixing it",
        waitsFor: null,
        position: 2
      }
    }
    const state = describePrState(pr)
    expect(state.kind).toBe('in-queue-conflict')
    expect(state.tone).toBe('blocked')
    expect(state.headline).toBe('Held in the queue: waiting on a conflict')
  })

  it('a PR in queue waiting on conflict AND with pr.conflicts returns conflict kind', () => {
    const pr = {
      ...basePr,
      conflicts: true,
      mergeQueue: {
        state: 'waiting',
        conflict: true,
        queued: true,
        reason: "Held: conflicts with main after #970 in src/app.js · MARVIN is fixing it",
        waitsFor: null,
        position: 2
      }
    }
    const state = describePrState(pr)
    expect(state.kind).toBe('conflict')
    expect(state.tone).toBe('blocked')
    expect(state.approve).toBe('hidden')
    expect(state.deny).toBe('enabled')
  })

  it('a queued conflict with pr.conflicts and repairFailed mentions the repair already failed', () => {
    const pr = {
      ...basePr,
      conflicts: true,
      repairFailed: true,
      mergeQueue: {
        state: 'waiting',
        conflict: true,
        queued: true,
        reason: "Held: conflicts with main after #970 in src/app.js · needs a rebuild",
        waitsFor: null,
        position: 2
      }
    }
    const state = describePrState(pr)
    expect(state.kind).toBe('conflict')
    expect(state.detail).toContain('needs a rebuild')
    expect(state.detail).not.toContain('The hourly scan tries to resolve it')
  })
})
