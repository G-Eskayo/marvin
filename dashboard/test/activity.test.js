import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { recordStage } from '../webhook-server/ticket_stages.js'
import { listTicketActivity, getTicketTimeline } from '../electron/main/activity.js'

function withTempDirs(fn) {
  const root = mkdtempSync(path.join(tmpdir(), 'activity-test-'))
  const stagesDir = path.join(root, 'ticket-stages')
  const statePath = path.join(root, 'dispatch-state.json')
  try {
    return fn({ root, stagesDir, statePath })
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
}

function writeDispatchState(statePath, content) {
  writeFileSync(statePath, JSON.stringify(content))
}

describe('getTicketTimeline', () => {
  it('returns the full event list for one ticket', () =>
    withTempDirs(({ stagesDir }) => {
      recordStage(42, 'claimed', 'started', '', { dir: stagesDir })
      recordStage(42, 'planning', 'started', '', { dir: stagesDir })
      const timeline = getTicketTimeline(42, stagesDir)
      expect(timeline.map((e) => e.stage)).toEqual(['claimed', 'planning'])
    }))

  it('returns an empty list for an untracked ticket', () =>
    withTempDirs(({ stagesDir }) => {
      expect(getTicketTimeline(999, stagesDir)).toEqual([])
    }))
})

describe('listTicketActivity', () => {
  it('summarizes each tracked ticket: current stage, total cost, failed flag', () =>
    withTempDirs(({ stagesDir, statePath }) => {
      writeDispatchState(statePath, { busy: false })
      recordStage(42, 'claimed', 'started', '', { dir: stagesDir, costUsd: null })
      recordStage(42, 'executing', 'started', '', { dir: stagesDir, costUsd: 0.01 })
      recordStage(42, 'executing', 'passed', '', { dir: stagesDir, costUsd: 0.02 })

      const [entry] = listTicketActivity(statePath, stagesDir)
      expect(entry.number).toBe(42)
      expect(entry.currentStage).toBe('executing')
      expect(entry.currentStatus).toBe('passed')
      expect(entry.costUsd).toBeCloseTo(0.03)
      expect(entry.failed).toBe(false)
      expect(entry.eventCount).toBe(3)
    }))

  it('flags a ticket as failed if any event in its timeline failed, even if it later recovered', () =>
    withTempDirs(({ stagesDir, statePath }) => {
      writeDispatchState(statePath, { busy: false })
      recordStage(42, 'verifying', 'failed', 'unchanged', { dir: stagesDir })
      recordStage(42, 'verifying', 'started', '', { dir: stagesDir })
      recordStage(42, 'verifying', 'passed', 'improved', { dir: stagesDir })

      const [entry] = listTicketActivity(statePath, stagesDir)
      expect(entry.failed).toBe(true)
      expect(entry.currentStatus).toBe('passed') // still reports the real current state
    }))

  it('marks a ticket isLiveNow when the dispatch state names it as the current task', () =>
    withTempDirs(({ stagesDir, statePath }) => {
      writeDispatchState(statePath, { busy: true, task: 'ticket #42: some title', started_at: new Date().toISOString() })
      recordStage(42, 'claimed', 'started', '', { dir: stagesDir })
      recordStage(99, 'claimed', 'started', '', { dir: stagesDir })

      const result = listTicketActivity(statePath, stagesDir)
      const byNumber = Object.fromEntries(result.map((e) => [e.number, e]))
      expect(byNumber[42].isLiveNow).toBe(true)
      expect(byNumber[99].isLiveNow).toBe(false)
    }))

  it('sorts live tickets first, then by most recently active', () =>
    withTempDirs(({ stagesDir, statePath }) => {
      writeDispatchState(statePath, { busy: true, task: 'ticket #30: x', started_at: new Date().toISOString() })
      recordStage(10, 'claimed', 'started', '', { dir: stagesDir })
      recordStage(30, 'claimed', 'started', '', { dir: stagesDir })
      recordStage(20, 'claimed', 'started', '', { dir: stagesDir })

      const result = listTicketActivity(statePath, stagesDir)
      expect(result[0].number).toBe(30) // live, goes first regardless of recency
    }))

  it('returns an empty list when nothing is tracked yet', () =>
    withTempDirs(({ stagesDir, statePath }) => {
      writeDispatchState(statePath, { busy: false })
      expect(listTicketActivity(statePath, stagesDir)).toEqual([])
    }))
})
