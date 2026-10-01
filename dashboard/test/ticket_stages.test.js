import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { recordStage, readStages, listTrackedTickets } from '../webhook-server/ticket_stages.js'

function withTempDir(fn) {
  const dir = mkdtempSync(path.join(tmpdir(), 'ticket-stages-test-'))
  try {
    return fn(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

describe('recordStage', () => {
  it('appends an event and returns it', () =>
    withTempDir((dir) => {
      const event = recordStage(42, 'gate', 'started', 'rebasing onto main', { dir, machine: 'mac-mini-1' })
      expect(event.stage).toBe('gate')
      expect(event.status).toBe('started')
      expect(event.detail).toBe('rebasing onto main')
      expect(event.machine).toBe('mac-mini-1')
      expect(event.cost_usd).toBe(null)
      expect(event.timestamp).toBeTruthy()
    }))

  it('rejects an unknown stage', () =>
    withTempDir((dir) => {
      expect(() => recordStage(42, 'not-a-stage', 'started', '', { dir })).toThrow(/unknown stage/)
    }))

  it('rejects an unknown status', () =>
    withTempDir((dir) => {
      expect(() => recordStage(42, 'gate', 'sideways', '', { dir })).toThrow(/unknown status/)
    }))

  it('carries an explicit cost_usd when given', () =>
    withTempDir((dir) => {
      const event = recordStage(42, 'merging', 'passed', '', { dir, costUsd: 0.0 })
      expect(event.cost_usd).toBe(0.0)
    }))

  it('resolves machine from resolveId when not given explicitly', () =>
    withTempDir((dir) => {
      const event = recordStage(42, 'gate', 'started', '', { dir, resolveId: () => 'macbook-pro-1' })
      expect(event.machine).toBe('macbook-pro-1')
    }))

  it('falls back to "unknown" when resolveId returns null', () =>
    withTempDir((dir) => {
      const event = recordStage(42, 'gate', 'started', '', { dir, resolveId: () => null })
      expect(event.machine).toBe('unknown')
    }))

  it('carries a title when given, defaults to null otherwise', () =>
    withTempDir((dir) => {
      const withTitle = recordStage(42, 'gate', 'started', '', { dir, title: 'Merge-time gate' })
      expect(withTitle.title).toBe('Merge-time gate')
      const withoutTitle = recordStage(43, 'gate', 'started', '', { dir })
      expect(withoutTitle.title).toBe(null)
    }))
})

describe('readStages', () => {
  it('returns events in append order, interleaving with what Python already wrote', () =>
    withTempDir((dir) => {
      recordStage(42, 'claimed', 'started', '', { dir, machine: 'mac-mini-1' })
      recordStage(42, 'gate', 'started', '', { dir, machine: 'mac-mini-1' })
      recordStage(42, 'gate', 'passed', '', { dir, machine: 'mac-mini-1' })
      const events = readStages(42, dir)
      expect(events.map((e) => e.stage)).toEqual(['claimed', 'gate', 'gate'])
    }))

  it('returns an empty list for an untracked ticket', () =>
    withTempDir((dir) => {
      expect(readStages(999, dir)).toEqual([])
    }))

  it('returns an empty list for a corrupt file rather than throwing', () =>
    withTempDir((dir) => {
      mkdirSync(dir, { recursive: true })
      writeFileSync(path.join(dir, '42.json'), 'not json')
      expect(readStages(42, dir)).toEqual([])
    }))
})

describe('listTrackedTickets', () => {
  it('returns sorted numeric ids, including ones written by the Python side', () =>
    withTempDir((dir) => {
      recordStage(117, 'claimed', 'started', '', { dir })
      recordStage(30, 'claimed', 'started', '', { dir })
      recordStage(94, 'claimed', 'started', '', { dir })
      expect(listTrackedTickets(dir)).toEqual([30, 94, 117])
    }))

  it('returns an empty list when the directory does not exist yet', () =>
    withTempDir((dir) => {
      expect(listTrackedTickets(path.join(dir, 'does-not-exist'))).toEqual([])
    }))
})
