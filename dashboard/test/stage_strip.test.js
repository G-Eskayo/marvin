import { describe, it, expect, beforeEach } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { deriveSegments } from '../src/lib/stage_strip.js'
import { recordStage, readStages } from '../webhook-server/ticket_stages.js'

const tmp = () => mkdtempSync(path.join(tmpdir(), 'stage-strip-'))

describe('deriveSegments', () => {
  describe('basic stage progression', () => {
    it('shows all stages up to and including done when all-passed', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0.01 },
        { stage: 'planning', status: 'passed', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0.02 },
        { stage: 'executing', status: 'passed', timestamp: '2026-10-01T02:00:00Z', machine: 'mini', cost_usd: 0.03 },
        { stage: 'done', status: 'passed', timestamp: '2026-10-01T03:00:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T04:00:00Z') })
      expect(segments).toHaveLength(4)
      expect(segments.map(s => s.stage)).toEqual(['claimed', 'planning', 'executing', 'done'])
      expect(segments.map(s => s.status)).toEqual(['passed', 'passed', 'passed', 'passed'])
    })

    it('does not trail pending segments after done', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'planning', status: 'passed', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'done', status: 'passed', timestamp: '2026-10-01T02:00:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T03:00:00Z') })
      expect(segments.map(s => s.stage)).toEqual(['claimed', 'planning', 'done'])
      // Should not have pending stages after done
      expect(segments.filter(s => s.status === 'pending')).toHaveLength(0)
    })
  })

  describe('pending stages (gap 1)', () => {
    it('renders pending/grey for stages without events up to the furthest stage', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'planning', status: 'passed', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0 }
        // No executing, verifying, gate events — they should show as pending
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T02:00:00Z') })
      const stageNames = segments.map(s => s.stage)
      expect(stageNames).toContain('executing')
      expect(stageNames).toContain('verifying')
      expect(stageNames).toContain('gate')
      const executing = segments.find(s => s.stage === 'executing')
      expect(executing.status).toBe('pending')
      expect(executing.events).toEqual([])
    })

    it('does not show pending stages before the first event', () => {
      const events = [
        { stage: 'executing', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T01:00:00Z') })
      const stageNames = segments.map(s => s.stage)
      expect(stageNames).not.toContain('claimed')
      expect(stageNames).not.toContain('planning')
      expect(stageNames.indexOf('executing')).toBeGreaterThanOrEqual(0)
    })
  })

  describe('failed stages with remediation (gap 2 partial - messages)', () => {
    it('parses plain CODE: message detail format (from merge.js)', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'gate', status: 'failed', detail: 'REBASE_CONFLICT: rebase onto main failed: merge conflict in src/main.js', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T02:00:00Z') })
      const gate = segments.find(s => s.stage === 'gate')
      expect(gate.status).toBe('failed')
      expect(gate.message).toContain('merge conflict in src/main.js')
      // REBASE_CONFLICT gets remediation text
      expect(gate.remediation).toContain('Rebase onto main failed')
    })

    it('parses refused CODE: message detail format (from refusal_log.js)', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'merging', status: 'failed', detail: 'refused OUT_OF_ORDER: ticket #158 has earlier PRs waiting', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T02:00:00Z') })
      const merging = segments.find(s => s.stage === 'merging')
      expect(merging.status).toBe('failed')
      expect(merging.message).toContain('ticket #158 has earlier PRs waiting')
      // OUT_OF_ORDER should be relabeled to "Order check"
      expect(merging.label).toBe('Order check')
    })

    it('shows pending stages after a failed stage', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'gate', status: 'failed', detail: 'GATE_TESTS_FAILED: test suite failed', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T02:00:00Z') })
      const stageNames = segments.map(s => s.stage)
      expect(stageNames).toContain('gate')
      expect(stageNames).toContain('merging')
      const merging = segments.find(s => s.stage === 'merging')
      expect(merging.status).toBe('pending')
    })
  })

  describe('mutation stage (gap 3)', () => {
    it('includes mutation stage in the valid vocabulary', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'planning', status: 'passed', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'mutation', status: 'started', timestamp: '2026-10-01T02:00:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T02:30:00Z'), isLiveNow: true })
      const mutation = segments.find(s => s.stage === 'mutation')
      expect(mutation).toBeDefined()
      expect(mutation.status).toBe('started')
    })
  })

  describe('liveness detection (gap 4 partial - isLiveNow)', () => {
    it('shows started as started when isLiveNow=true and timestamp is recent', () => {
      const now = Date.parse('2026-10-01T02:00:00Z')
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'executing', status: 'started', timestamp: '2026-10-01T01:50:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now, isLiveNow: true })
      const executing = segments.find(s => s.stage === 'executing')
      expect(executing.status).toBe('started')
    })

    it('shows started as stalled when isLiveNow=false regardless of timestamp', () => {
      const now = Date.parse('2026-10-01T02:00:00Z')
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'executing', status: 'started', timestamp: '2026-10-01T01:59:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now, isLiveNow: false })
      const executing = segments.find(s => s.stage === 'executing')
      expect(executing.status).toBe('stalled')
    })

    it('shows started as stalled when isLiveNow=true but elapsed time exceeds stallMinutes', () => {
      const now = Date.parse('2026-10-01T02:00:00Z')
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'executing', status: 'started', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0 }
        // 60 minutes elapsed, default stallMinutes is 30
      ]
      const segments = deriveSegments(events, { now, isLiveNow: true, stallMinutes: 30 })
      const executing = segments.find(s => s.stage === 'executing')
      expect(executing.status).toBe('stalled')
    })

    it('respects custom stallMinutes value', () => {
      const now = Date.parse('2026-10-01T02:00:00Z')
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'executing', status: 'started', timestamp: '2026-10-01T01:30:00Z', machine: 'mini', cost_usd: 0 }
        // 30 minutes elapsed
      ]
      // With stallMinutes=60, should still be started
      const segments = deriveSegments(events, { now, isLiveNow: true, stallMinutes: 60 })
      const executing = segments.find(s => s.stage === 'executing')
      expect(executing.status).toBe('started')
    })
  })

  describe('full event history per stage (gap 4 partial - events array)', () => {
    it('keeps all events for a stage in the segment, not just latest', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'executing', status: 'failed', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0.5, detail: 'Test timeout' },
        { stage: 'executing', status: 'started', timestamp: '2026-10-01T01:05:00Z', machine: 'mini', cost_usd: 0.5 },
        { stage: 'executing', status: 'passed', timestamp: '2026-10-01T02:00:00Z', machine: 'mini', cost_usd: 0.5 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T03:00:00Z') })
      const executing = segments.find(s => s.stage === 'executing')
      expect(executing.events).toHaveLength(3)
      expect(executing.events[0].status).toBe('failed')
      expect(executing.events[1].status).toBe('started')
      expect(executing.events[2].status).toBe('passed')
    })

    it('uses latest status for the segment headline but preserves full history', () => {
      const events = [
        { stage: 'executing', status: 'failed', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'executing', status: 'passed', timestamp: '2026-10-01T02:00:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T03:00:00Z') })
      const executing = segments.find(s => s.stage === 'executing')
      expect(executing.status).toBe('passed')
      expect(executing.events).toHaveLength(2)
    })
  })

  describe('segment data (gap 2 - machine and cost_usd)', () => {
    it('includes machine and cost_usd in the segment', () => {
      const events = [
        { stage: 'executing', status: 'passed', timestamp: '2026-10-01T01:00:00Z', machine: 'mac-mini', cost_usd: 1.23 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T02:00:00Z') })
      expect(segments[0].machine).toBe('mac-mini')
      expect(segments[0].cost_usd).toBe(1.23)
    })

    it('handles missing machine/cost_usd gracefully', () => {
      const events = [
        { stage: 'executing', status: 'passed', timestamp: '2026-10-01T01:00:00Z' }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T02:00:00Z') })
      expect(segments[0].machine).toBeUndefined()
      expect(segments[0].cost_usd).toBeUndefined()
    })
  })

  describe('rebase conflict handling', () => {
    it('handles rebase with status=conflict and files array', () => {
      const segments = deriveSegments(
        [{ stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 }],
        { now: Date.parse('2026-10-01T01:00:00Z'), rebase: { status: 'conflict', files: ['src/main.js', 'src/util.js'] } }
      )
      const rebase = segments.find(s => s.stage === 'rebase')
      expect(rebase).toBeDefined()
      expect(rebase.status).toBe('failed')
    })

    it('handles rebase with status=conflict but no files array', () => {
      const segments = deriveSegments(
        [{ stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 }],
        { now: Date.parse('2026-10-01T01:00:00Z'), rebase: { status: 'conflict' } }
      )
      const rebase = segments.find(s => s.stage === 'rebase')
      expect(rebase.status).toBe('failed')
      expect(rebase.message).toBeTruthy()
    })
  })

  describe('error handling (gap 5 - dead entry cleanup)', () => {
    it('never throws on empty/null input', () => {
      expect(() => deriveSegments({})).not.toThrow()
      expect(() => deriveSegments(null)).not.toThrow()
      expect(() => deriveSegments(undefined)).not.toThrow()
      expect(() => deriveSegments([])).not.toThrow()
    })

    it('ignores entries with missing or unknown stage name', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'unknown-future-stage', status: 'passed', timestamp: '2026-10-01T01:00:00Z', machine: 'mini', cost_usd: 0 }
      ]
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T02:00:00Z') })
      expect(segments.some(s => s.stage === 'unknown-future-stage')).toBe(false)
    })

    it('ignores events with garbage/unparseable timestamp', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 },
        { stage: 'planning', status: 'passed', timestamp: 'not-a-date', machine: 'mini', cost_usd: 0 }
      ]
      expect(() => deriveSegments(events, { now: Date.parse('2026-10-01T02:00:00Z') })).not.toThrow()
    })

    it('degrades gracefully for missing cost_usd/machine on some events', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 1.0 },
        { stage: 'planning', status: 'passed', timestamp: '2026-10-01T01:00:00Z' }
      ]
      expect(() => deriveSegments(events, { now: Date.parse('2026-10-01T02:00:00Z') })).not.toThrow()
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T02:00:00Z') })
      const planning = segments.find(s => s.stage === 'planning')
      expect(planning).toBeDefined()
    })
  })

  describe('huge/pathological input', () => {
    it('handles hundreds of retries on one stage without blowing up', () => {
      const events = [
        { stage: 'claimed', status: 'passed', timestamp: '2026-10-01T00:00:00Z', machine: 'mini', cost_usd: 0 }
      ]
      for (let i = 0; i < 100; i++) {
        const hour = 1 + Math.floor(i / 60)
        const minute = i % 60
        events.push({ stage: 'executing', status: i % 2 === 0 ? 'failed' : 'started', timestamp: `2026-10-01T${hour.toString().padStart(2, '0')}:${minute.toString().padStart(2, '0')}:00Z`, machine: 'mini', cost_usd: 0.1 })
      }
      const start = Date.now()
      const segments = deriveSegments(events, { now: Date.parse('2026-10-01T03:00:00Z') })
      const elapsed = Date.now() - start
      expect(elapsed).toBeLessThan(1000)
      // segments = [claimed (idx 0), planning (idx 1), executing (idx 2)]
      const executing = segments.find(s => s.stage === 'executing')
      expect(executing.events).toHaveLength(100)
    })
  })

  describe('integration with real ticket_stages.js writer', () => {
    it('parses and displays real stage logs from recordStage', () => {
      const dir = tmp()
      try {
        recordStage(1, 'claimed', 'passed', '', { machine: 'mac-mini', costUsd: 0.01, title: 'Test PR', dir, resolveId: () => 'mac-mini' })
        recordStage(1, 'planning', 'passed', '', { machine: 'mac-mini', costUsd: 0.02, dir, resolveId: () => 'mac-mini' })
        recordStage(1, 'executing', 'failed', 'Test timeout after 10m', { machine: 'mac-mini', costUsd: 0.05, dir, resolveId: () => 'mac-mini' })
        recordStage(1, 'executing', 'started', '', { machine: 'mac-mini', costUsd: 0.05, dir, resolveId: () => 'mac-mini' })

        const events = readStages(1, dir, 'G-Eskayo/marvin')
        const segments = deriveSegments(events, { now: Date.parse('2026-10-01T12:00:00Z'), isLiveNow: true })

        // Stages with events: claimed, planning, executing
        // Since executing is not terminal, show pending up to merging
        // So: claimed, planning, executing, verifying, gate, mutation, merging (7 segments)
        const withEvents = segments.filter(s => s.events.length > 0)
        expect(withEvents).toHaveLength(3)
        expect(withEvents.map(s => s.stage)).toEqual(['claimed', 'planning', 'executing'])
        const executing = withEvents[2]
        expect(executing.status).toBe('started')
        expect(executing.events).toHaveLength(2)
        expect(executing.events[0].status).toBe('failed')
        expect(executing.events[1].status).toBe('started')
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })
})
