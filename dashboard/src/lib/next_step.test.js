import { describe, it, expect } from 'vitest'
import { prStep } from './next_step.js'

describe('next_step: conflict handling with needs a rebuild', () => {
  const basePr = {
    number: 972,
    repo: 'G-Eskayo/marvin',
    title: 'Fix conflict',
    url: 'https://github.com/G-Eskayo/marvin/pull/972',
    isDraft: false,
    checks: { state: 'passing', failing: [], pending: [] },
    createdAt: new Date(Date.now() - 1000).toISOString()
  }

  it('the "needs a rebuild" substring in conflict reason marks PR as stuck', () => {
    const pr = {
      ...basePr,
      conflicts: true,
      mergeQueue: {
        reason: "Held: conflicts with main after #970 in src/app.js · needs a rebuild"
      }
    }
    const step = prStep(pr)
    // When a conflict has "needs a rebuild", it's stuck
    expect(step.owner).toBe('nobody')
    expect(step.verb).toBe('Needs a rebuild')
    expect(step.section).toBe('stuck')
  })

  it('without needs a rebuild, conflict is being fixed by MARVIN', () => {
    const pr = {
      ...basePr,
      conflicts: true,
      mergeQueue: {
        reason: "Held: conflicts with main after #970 · MARVIN is fixing it"
      }
    }
    const step = prStep(pr)
    expect(step.owner).toBe('marvin')
    expect(step.verb).toBe('Fixing a conflict')
    expect(step.section).toBe('marvin')
    expect(step.phase).toBe('review')
  })

  it('conflict in queue with needs a rebuild is stuck, even with mq.state', () => {
    const pr = {
      ...basePr,
      conflicts: true,
      mergeQueue: {
        state: 'waiting',
        conflict: true,
        queued: true,
        reason: "Held: conflicts with main after #970 in src/app.js · needs a rebuild",
        position: 2
      }
    }
    const step = prStep(pr)
    expect(step.owner).toBe('nobody')
    expect(step.verb).toBe('Needs a rebuild')
    expect(step.section).toBe('stuck')
  })

  it('conflict in queue being fixed by MARVIN is marvin section, even with mq.state', () => {
    const pr = {
      ...basePr,
      conflicts: true,
      mergeQueue: {
        state: 'waiting',
        conflict: true,
        queued: true,
        reason: "Held: conflicts with main after #970 · MARVIN is fixing it",
        position: 2
      }
    }
    const step = prStep(pr)
    expect(step.owner).toBe('marvin')
    expect(step.verb).toBe('Fixing a conflict')
    expect(step.section).toBe('marvin')
    expect(step.phase).toBe('review')
  })
})
