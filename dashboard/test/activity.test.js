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

  it('surfaces the title from whichever event carried it, not just the last one', () =>
    withTempDirs(({ stagesDir, statePath }) => {
      writeDispatchState(statePath, { busy: false })
      recordStage(42, 'claimed', 'started', '', { dir: stagesDir, title: 'Versioning: VERSION + CHANGELOG.md bump' })
      recordStage(42, 'executing', 'started', '', { dir: stagesDir }) // no title on later events

      const [entry] = listTicketActivity(statePath, stagesDir)
      expect(entry.title).toBe('Versioning: VERSION + CHANGELOG.md bump')
    }))

  it('reports title: null when no event in the timeline has one (never a bare-number dead end)', () =>
    withTempDirs(({ stagesDir, statePath }) => {
      writeDispatchState(statePath, { busy: false })
      recordStage(42, 'claimed', 'started', '', { dir: stagesDir })

      const [entry] = listTicketActivity(statePath, stagesDir)
      expect(entry.title).toBe(null)
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

// marvin#127: ticket numbers are per repository. #13 in clarity-captions is not #13 in marvin, but the Activity
// code asked for timelines and live tasks by bare number, so one project's card showed another's history.
describe('activity is keyed by project and number, never by number alone (marvin #127)', () => {
  const CC = 'G-Eskayo/clarity-captions'
  const MV = 'G-Eskayo/marvin'

  it('getTicketTimeline reads the right project\'s history when both have the same ticket number', () =>
    withTempDirs(({ stagesDir }) => {
      recordStage(13, 'claimed', 'started', '', { dir: stagesDir })                          // marvin #13
      recordStage(13, 'executing', 'started', '', { dir: stagesDir, repo: CC })              // clarity-captions #13
      recordStage(13, 'done', 'passed', 'merged', { dir: stagesDir, repo: CC })
      expect(getTicketTimeline(13, stagesDir, MV).map((e) => e.stage)).toEqual(['claimed'])
      expect(getTicketTimeline(13, stagesDir, CC).map((e) => e.stage)).toEqual(['executing', 'done'])
      expect(getTicketTimeline(13, stagesDir).map((e) => e.stage)).toEqual(['claimed']) // no repo = marvin, as before
    }))

  it('listTicketActivity lists every project\'s tickets, each tagged with its repo and a repo#number key', () =>
    withTempDirs(({ stagesDir, statePath }) => {
      writeDispatchState(statePath, { busy: false })
      recordStage(13, 'claimed', 'started', '', { dir: stagesDir })
      recordStage(13, 'done', 'passed', 'merged', { dir: stagesDir, repo: CC })
      recordStage(2, 'executing', 'failed', '', { dir: stagesDir, repo: 'G-Eskayo/finance-os' })
      const rows = listTicketActivity(statePath, stagesDir)
      expect(rows.map((r) => r.key).sort()).toEqual([`G-Eskayo/finance-os#2`, `${CC}#13`, `${MV}#13`].sort())
      const cc = rows.find((r) => r.key === `${CC}#13`)
      expect(cc).toMatchObject({ repo: CC, number: 13, currentStage: 'done' })
      expect(rows.find((r) => r.key === `${MV}#13`)).toMatchObject({ repo: MV, currentStage: 'claimed' })
    }))

  it('a running task is matched to its own project: "ticket #13" is marvin, "ticket <repo>#13" is that repo', () =>
    withTempDirs(({ stagesDir, statePath }) => {
      recordStage(13, 'executing', 'started', '', { dir: stagesDir })
      recordStage(13, 'executing', 'started', '', { dir: stagesDir, repo: CC })
      writeDispatchState(statePath, { busy: true, task: `ticket ${CC}#13: Accessibility pass` })
      let rows = listTicketActivity(statePath, stagesDir)
      expect(rows.find((r) => r.key === `${CC}#13`).isLiveNow).toBe(true)
      expect(rows.find((r) => r.key === `${MV}#13`).isLiveNow).toBe(false)

      writeDispatchState(statePath, { busy: true, task: 'ticket #13: Dashboard thing' })
      rows = listTicketActivity(statePath, stagesDir)
      expect(rows.find((r) => r.key === `${MV}#13`).isLiveNow).toBe(true)
      expect(rows.find((r) => r.key === `${CC}#13`).isLiveNow).toBe(false)
    }))

  it('does not confuse #13 with #130', () =>
    withTempDirs(({ stagesDir, statePath }) => {
      recordStage(13, 'executing', 'started', '', { dir: stagesDir })
      writeDispatchState(statePath, { busy: true, task: 'ticket #130: something else' })
      expect(listTicketActivity(statePath, stagesDir)[0].isLiveNow).toBe(false)
    }))
})

