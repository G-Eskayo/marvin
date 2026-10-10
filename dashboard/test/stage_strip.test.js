import { describe, it, expect } from 'vitest'
import { deriveStageStrip, extractCode, remediationFor, formatElapsed, STAGE_LABEL, REMEDIATION_BY_CODE } from '../src/lib/stage_strip.js'

describe('stage_strip', () => {
  describe('extractCode', () => {
    it('extracts code from "CODE: detail" format', () => {
      expect(extractCode('OUT_OF_ORDER: Merge #208 first')).toBe('OUT_OF_ORDER')
      expect(extractCode('REBASE_CONFLICT: after PR #42 merged')).toBe('REBASE_CONFLICT')
    })

    it('returns null for bare message with no code', () => {
      expect(extractCode('some generic error message')).toBe(null)
    })

    it('returns null for empty string', () => {
      expect(extractCode('')).toBe(null)
      expect(extractCode(null)).toBe(null)
    })
  })

  describe('remediationFor', () => {
    it('looks up known codes', () => {
      const rem = remediationFor('OUT_OF_ORDER')
      expect(rem).toBeTruthy()
      expect(rem).toContain('must merge first')
    })

    it('returns null for unknown code', () => {
      expect(remediationFor('UNKNOWN_CODE')).toBe(null)
    })

    it('returns null for null input', () => {
      expect(remediationFor(null)).toBe(null)
    })
  })

  describe('formatElapsed', () => {
    it('formats milliseconds as human-readable durations', () => {
      expect(formatElapsed(1500)).toBe('1s')
      expect(formatElapsed(90_000)).toBe('1m 30s')
      expect(formatElapsed(3661_000)).toBe('1h 1m')
    })

    it('handles zero and negatives', () => {
      expect(formatElapsed(0)).toBe('0s')
      expect(formatElapsed(-1000)).toBe('0s')
    })
  })

  describe('deriveStageStrip', () => {
    it('returns all stages pending when given no events', () => {
      const segments = deriveStageStrip([])
      expect(segments).toHaveLength(9) // claimed through done
      expect(segments.every((s) => s.status === 'pending')).toBe(true)
    })

    it('marks stages as passed/failed based on events', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: new Date().toISOString() },
        { stage: 'planning', status: 'failed', detail: 'OUT_OF_ORDER: Merge #208 first', timestamp: new Date().toISOString() }
      ]
      const segments = deriveStageStrip(events)
      expect(segments.find((s) => s.stage === 'claimed').status).toBe('passed')
      expect(segments.find((s) => s.stage === 'planning').status).toBe('failed')
      expect(segments.find((s) => s.stage === 'planning').code).toBe('OUT_OF_ORDER')
    })

    it('keeps latest status only for repeated stages', () => {
      const events = [
        { stage: 'merging', status: 'started', timestamp: new Date(Date.now() - 5 * 60_000).toISOString() },
        { stage: 'merging', status: 'failed', detail: 'CI_FAILED: tests', timestamp: new Date().toISOString() }
      ]
      const segments = deriveStageStrip(events)
      const merging = segments.find((s) => s.stage === 'merging')
      expect(merging.status).toBe('failed')
      expect(merging.code).toBe('CI_FAILED')
    })

    it('marks stage as stalled when started is too old', () => {
      const now = Date.now()
      const oldTimestamp = new Date(now - 11 * 60_000).toISOString() // 11 minutes ago
      const events = [
        { stage: 'claimed', status: 'started', timestamp: oldTimestamp }
      ]
      const segments = deriveStageStrip(events, { now })
      expect(segments.find((s) => s.stage === 'claimed').status).toBe('stalled')
    })

    it('marks stage as running when started is recent', () => {
      const now = Date.now()
      const recentTimestamp = new Date(now - 2 * 60_000).toISOString() // 2 minutes ago
      const events = [
        { stage: 'claimed', status: 'started', timestamp: recentTimestamp }
      ]
      const segments = deriveStageStrip(events, { now })
      expect(segments.find((s) => s.stage === 'claimed').status).toBe('running')
    })

    it('respects isLiveNow as a positive signal', () => {
      const now = Date.now()
      const oldTimestamp = new Date(now - 50 * 60_000).toISOString() // 50 min old
      const events = [
        { stage: 'gate', status: 'started', timestamp: oldTimestamp }
      ]
      // Without isLiveNow, it's stalled (50min > 35min gate threshold)
      const noLive = deriveStageStrip(events, { now })
      expect(noLive.find((s) => s.stage === 'gate').status).toBe('stalled')

      // With isLiveNow true, it's running
      const withLive = deriveStageStrip(events, { now, liveOverlay: { isLiveNow: true } })
      expect(withLive.find((s) => s.stage === 'gate').status).toBe('running')

      // With isLiveNow false, still stalled (false doesn't prove it's not running elsewhere)
      const falseLive = deriveStageStrip(events, { now, liveOverlay: { isLiveNow: false } })
      expect(falseLive.find((s) => s.stage === 'gate').status).toBe('stalled')
    })

    it('marks gate-failed as "needs-rebase" when code is REBASE_CONFLICT', () => {
      const events = [
        { stage: 'gate', status: 'failed', detail: 'REBASE_CONFLICT: after PR #42 merged', timestamp: new Date().toISOString() }
      ]
      const segments = deriveStageStrip(events)
      const gate = segments.find((s) => s.stage === 'gate')
      expect(gate.status).toBe('needs-rebase')
      expect(gate.code).toBe('REBASE_CONFLICT')
    })

    it('extracts remediation for failed stages', () => {
      const events = [
        { stage: 'merging', status: 'failed', detail: 'VERSION_BUMP_FAILED: bad format', timestamp: new Date().toISOString() }
      ]
      const segments = deriveStageStrip(events)
      const merging = segments.find((s) => s.stage === 'merging')
      expect(merging.remediation).toBeTruthy()
      expect(merging.remediation).toContain('Version bump')
    })

    it('gracefully handles malformed events (missing timestamp, etc.)', () => {
      const events = [
        { stage: 'claimed', status: 'passed' }, // no timestamp
        { stage: 'planning', status: 'started', timestamp: null }
      ]
      // Should not throw
      const segments = deriveStageStrip(events)
      expect(segments).toHaveLength(9)
      expect(segments.find((s) => s.stage === 'claimed').status).toBe('passed')
      expect(segments.find((s) => s.stage === 'planning').status).toBe('pending') // falls through to pending
    })

    it('computes elapsed time for running segments', () => {
      const now = Date.now()
      const eventTime = new Date(now - 2 * 60_000).toISOString()
      const events = [
        { stage: 'executing', status: 'started', timestamp: eventTime }
      ]
      const segments = deriveStageStrip(events, { now })
      const executing = segments.find((s) => s.stage === 'executing')
      expect(executing.status).toBe('running')
      expect(executing.elapsed).toBeCloseTo(2 * 60_000, -3) // within 1 second
    })
  })

  describe('REMEDIATION_BY_CODE', () => {
    it('includes remediations for all codes used in failure.js', () => {
      const requiredCodes = [
        'GH_AUTH_INVALID', 'NOT_MERGEABLE', 'PR_DRAFT', 'BRANCH_PROTECTION',
        'BASE_MOVED', 'RATE_LIMITED', 'GITHUB_OUTAGE', 'TRANSIENT_NETWORK',
        'TOOL_MISSING', 'PR_NOT_FOUND', 'INVALID_REQUEST'
      ]
      requiredCodes.forEach((code) => {
        expect(REMEDIATION_BY_CODE[code]).toBeTruthy()
      })
    })

    it('includes remediations for inline refusal codes', () => {
      const inlineRefusalCodes = [
        'OUT_OF_ORDER', 'WRONG_BASE', 'SENT_BACK', 'CI_PENDING',
        'NO_MERGE_PROFILE', 'MERGE_REFUSED', 'CI_FAILED', 'GATE_INFRA',
        'MAIN_RED', 'GATE_TESTS_FAILED', 'VERSION_BUMP_FAILED', 'REBASE_CONFLICT'
      ]
      inlineRefusalCodes.forEach((code) => {
        expect(REMEDIATION_BY_CODE[code]).toBeTruthy()
      })
    })
  })

  describe('STAGE_LABEL', () => {
    it('maps all stages to display labels', () => {
      const stages = ['claimed', 'planning', 'executing', 'verifying', 'gate', 'merging', 'versioning', 'rebuilding', 'done']
      stages.forEach((stage) => {
        expect(STAGE_LABEL[stage]).toBeTruthy()
      })
    })
  })
})
