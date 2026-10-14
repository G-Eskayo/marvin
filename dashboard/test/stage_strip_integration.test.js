import { describe, it, expect, afterEach } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { deriveSegments } from '../src/lib/stage_strip'
import { recordStage, readStages, stageKey } from '../webhook-server/ticket_stages.js'
import { recordRefusal, REFUSAL_CODES } from '../webhook-server/refusal_log.js'

describe('deriveSegments with real stage events', () => {
  let tmpDir

  afterEach(() => {
    if (tmpDir) {
      try {
        rmSync(tmpDir, { recursive: true })
      } catch {}
    }
  })

  // Test 23: Real recordStage output integrated with deriveSegments
  it('derives correct segments from real recordStage output', () => {
    tmpDir = mkdtempSync(path.join(tmpdir(), 'stage-test-'))

    recordStage(7, 'claimed', 'passed', 'Claimed by Alice', { dir: tmpDir })
    recordStage(7, 'planning', 'passed', 'Plan created', { dir: tmpDir })
    recordStage(7, 'gate', 'started', 'Running tests', { dir: tmpDir })

    const events = readStages(7, tmpDir)
    // isLiveNow=true keeps recent 'started' as started, otherwise it becomes 'stalled'
    const segments = deriveSegments(events, { isLiveNow: true, stallMinutes: 60 })

    expect(segments.length).toBe(3)
    expect(segments[0].stage).toBe('claimed')
    expect(segments[0].status).toBe('passed')
    expect(segments[1].stage).toBe('planning')
    expect(segments[2].stage).toBe('gate')
    expect(segments[2].status).toBe('started')
  })

  // Test 24: Real recordRefusal output with OUT_OF_ORDER
  it('maps OUT_OF_ORDER from real recordRefusal to order segment', () => {
    tmpDir = mkdtempSync(path.join(tmpdir(), 'refusal-test-'))

    recordStage(9, 'claimed', 'passed', 'Claimed', { dir: tmpDir })

    // Simulate what recordRefusal does when writeStage=true and code is OUT_OF_ORDER
    recordRefusal(
      {
        prUrl: 'https://github.com/G-Eskayo/marvin/pull/999',
        ticket: 9,
        code: 'OUT_OF_ORDER',
        message: 'Merge #208 first',
        stage: 'order'
      },
      {
        recordStageFn: (ticketNumber, stage, status, detail, opts) =>
          recordStage(ticketNumber, stage, status, detail, { ...opts, dir: tmpDir }),
        writeStage: true
      }
    )

    const events = readStages(9, tmpDir)
    const segments = deriveSegments(events)

    const orderSegment = segments.find(s => s.stage === 'order')
    expect(orderSegment).toBeDefined()
    expect(orderSegment.status).toBe('failed')
    expect(orderSegment.message).toContain('Merge #208')
  })

  // Test 24b: WRONG_BASE refusal
  it('maps WRONG_BASE from real recordRefusal to order segment', () => {
    tmpDir = mkdtempSync(path.join(tmpdir(), 'wrong-base-test-'))

    recordStage(10, 'claimed', 'passed', 'Claimed', { dir: tmpDir })

    recordRefusal(
      {
        prUrl: 'https://github.com/G-Eskayo/marvin/pull/1000',
        ticket: 10,
        code: 'WRONG_BASE',
        message: 'Rebase onto main',
        stage: 'order'
      },
      {
        recordStageFn: (ticketNumber, stage, status, detail, opts) =>
          recordStage(ticketNumber, stage, status, detail, { ...opts, dir: tmpDir }),
        writeStage: true
      }
    )

    const events = readStages(10, tmpDir)
    const segments = deriveSegments(events)

    const orderSegment = segments.find(s => s.stage === 'order')
    expect(orderSegment).toBeDefined()
    expect(orderSegment.status).toBe('failed')
  })

  // Test 24c: Other refusal codes go to request
  it('maps SENT_BACK from real recordRefusal to request segment', () => {
    tmpDir = mkdtempSync(path.join(tmpdir(), 'sent-back-test-'))

    recordStage(11, 'claimed', 'passed', 'Claimed', { dir: tmpDir })

    recordRefusal(
      {
        prUrl: 'https://github.com/G-Eskayo/marvin/pull/1001',
        ticket: 11,
        code: 'SENT_BACK',
        message: 'Rework needed',
        stage: 'request'
      },
      {
        recordStageFn: (ticketNumber, stage, status, detail, opts) =>
          recordStage(ticketNumber, stage, status, detail, { ...opts, dir: tmpDir }),
        writeStage: true
      }
    )

    const events = readStages(11, tmpDir)
    const segments = deriveSegments(events)

    const requestSegment = segments.find(s => s.stage === 'request')
    expect(requestSegment).toBeDefined()
    expect(requestSegment.status).toBe('failed')
  })

  // Test 24d: CI_PENDING refusal
  it('maps CI_PENDING from real recordRefusal to request segment', () => {
    tmpDir = mkdtempSync(path.join(tmpdir(), 'ci-pending-test-'))

    recordRefusal(
      {
        prUrl: 'https://github.com/G-Eskayo/marvin/pull/1002',
        ticket: 12,
        code: 'CI_PENDING',
        message: 'Waiting for checks',
        stage: 'request'
      },
      {
        recordStageFn: (ticketNumber, stage, status, detail, opts) =>
          recordStage(ticketNumber, stage, status, detail, { ...opts, dir: tmpDir }),
        writeStage: true
      }
    )

    const events = readStages(12, tmpDir)
    const segments = deriveSegments(events)

    const requestSegment = segments.find(s => s.stage === 'request')
    expect(requestSegment).toBeDefined()
  })

  // Test 25: Multi-repo stage keys work
  it('reads stage events for tickets in different projects', () => {
    tmpDir = mkdtempSync(path.join(tmpdir(), 'multi-repo-test-'))

    // Record for marvin
    recordStage(13, 'claimed', 'passed', 'Claimed', { dir: tmpDir })

    // Record for another project
    recordStage(13, 'planning', 'passed', 'Planning', {
      dir: tmpDir,
      repo: 'G-Eskayo/clarity-captions'
    })

    const marvinEvents = readStages(13, tmpDir, 'G-Eskayo/marvin')
    const clarityEvents = readStages(13, tmpDir, 'G-Eskayo/clarity-captions')

    expect(marvinEvents.length).toBe(1)
    expect(marvinEvents[0].stage).toBe('claimed')

    expect(clarityEvents.length).toBe(1)
    expect(clarityEvents[0].stage).toBe('planning')
  })

  // Test 26: Full pipeline run is preserved
  it('preserves complete pipeline run from claimed to done', () => {
    tmpDir = mkdtempSync(path.join(tmpdir(), 'full-pipeline-test-'))

    const stages = ['claimed', 'planning', 'executing', 'verifying', 'gate', 'mutation', 'merging', 'versioning', 'rebuilding', 'done']
    for (const stage of stages) {
      recordStage(14, stage, 'passed', `Completed ${stage}`, { dir: tmpDir })
    }

    const events = readStages(14, tmpDir)
    const segments = deriveSegments(events)

    expect(segments.length).toBe(10)
    for (let i = 0; i < 10; i++) {
      expect(segments[i].stage).toBe(stages[i])
      expect(segments[i].status).toBe('passed')
    }
  })
})
