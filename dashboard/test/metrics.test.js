import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync } from 'fs'
import { join } from 'path'
import { tmpdir } from 'os'
import { listSubsystems, readHistory, latest, buildIndex } from '../electron/main/metrics.js'

let dir

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'metrics-test-'))
})

afterEach(() => {
  rmSync(dir, { recursive: true, force: true })
})

describe('listSubsystems', () => {
  it('returns an empty list when the metrics dir does not exist', () => {
    expect(listSubsystems(join(dir, 'nonexistent'))).toEqual([])
  })

  it('returns sorted subsystem names from .json files, ignoring others', () => {
    writeFileSync(join(dir, 'zeta.json'), '[]')
    writeFileSync(join(dir, 'alpha.json'), '[]')
    writeFileSync(join(dir, 'index.md'), '# not a subsystem')
    expect(listSubsystems(dir)).toEqual(['alpha', 'zeta'])
  })
})

describe('readHistory', () => {
  it('returns an empty list when the subsystem file does not exist', () => {
    expect(readHistory('missing', dir)).toEqual([])
  })

  it('returns the full snapshot list for an existing subsystem, tagged with machine', () => {
    const snapshots = [
      { timestamp: '2026-01-01T00:00:00Z', metrics: { accuracy: { value: 0.8, higher_is_better: true } } },
      { timestamp: '2026-01-02T00:00:00Z', metrics: { accuracy: { value: 0.9, higher_is_better: true } } }
    ]
    writeFileSync(join(dir, 'route.json'), JSON.stringify(snapshots))
    const result = readHistory('route', dir)
    expect(result).toHaveLength(2)
    expect(result[0]).toMatchObject({ timestamp: '2026-01-01T00:00:00Z', metrics: snapshots[0].metrics })
    expect(result[0].machine).toBe('legacy')
    expect(result[1]).toMatchObject({ timestamp: '2026-01-02T00:00:00Z', metrics: snapshots[1].metrics })
    expect(result[1].machine).toBe('legacy')
  })

  it('returns an empty list instead of throwing on corrupt JSON', () => {
    writeFileSync(join(dir, 'broken.json'), '{not valid json')
    expect(readHistory('broken', dir)).toEqual([])
  })

  it('returns an empty list if the JSON is valid but not an array', () => {
    writeFileSync(join(dir, 'wrongshape.json'), '{"oops": true}')
    expect(readHistory('wrongshape', dir)).toEqual([])
  })

  it('merges histories from multiple machines into one sorted timeline', () => {
    // Mini has entries from Jan 1 and Jan 3
    writeFileSync(
      join(dir, 'route.mac-mini.json'),
      JSON.stringify([
        { timestamp: '2026-01-01T00:00:00Z', metrics: { acc: { value: 0.7, higher_is_better: true } } },
        { timestamp: '2026-01-03T00:00:00Z', metrics: { acc: { value: 0.8, higher_is_better: true } } }
      ])
    )
    // Laptop has an entry from Jan 2 (between the Mini's entries)
    writeFileSync(
      join(dir, 'route.macbook-pro.json'),
      JSON.stringify([
        { timestamp: '2026-01-02T00:00:00Z', metrics: { acc: { value: 0.75, higher_is_better: true } } }
      ])
    )
    const result = readHistory('route', dir)
    expect(result).toHaveLength(3)
    // Should be sorted by timestamp
    expect(result[0].timestamp).toBe('2026-01-01T00:00:00Z')
    expect(result[0].machine).toBe('mac-mini')
    expect(result[1].timestamp).toBe('2026-01-02T00:00:00Z')
    expect(result[1].machine).toBe('macbook-pro')
    expect(result[2].timestamp).toBe('2026-01-03T00:00:00Z')
    expect(result[2].machine).toBe('mac-mini')
  })
})

describe('latest', () => {
  it('returns null when there is no history', () => {
    expect(latest('missing', dir)).toBeNull()
  })

  it('returns the last snapshot, not the first, tagged with machine', () => {
    const snapshots = [
      { timestamp: '2026-01-01T00:00:00Z', metrics: { x: { value: 1, higher_is_better: true } } },
      { timestamp: '2026-01-02T00:00:00Z', metrics: { x: { value: 2, higher_is_better: true } } }
    ]
    writeFileSync(join(dir, 'route.json'), JSON.stringify(snapshots))
    const result = latest('route', dir)
    expect(result).toMatchObject(snapshots[1])
    expect(result.machine).toBe('legacy')
  })
})

describe('buildIndex', () => {
  it('returns an empty object when no subsystems exist', () => {
    expect(buildIndex(join(dir, 'nonexistent'))).toEqual({})
  })

  it('maps each subsystem to its latest snapshot across all machines, skipping empty ones', () => {
    writeFileSync(
      join(dir, 'route.json'),
      JSON.stringify([{ timestamp: 't1', metrics: { acc: { value: 1, higher_is_better: true } } }])
    )
    writeFileSync(join(dir, 'empty.json'), '[]')
    const index = buildIndex(dir)
    expect(Object.keys(index)).toEqual(['route'])
    expect(index.route.metrics.acc.value).toBe(1)
    expect(index.route.machine).toBe('legacy')
  })

  it('merges multiple machines and returns the newest timestamp across all machines', () => {
    // Mini has an entry from 2026-01-01
    writeFileSync(
      join(dir, 'route.mac-mini.json'),
      JSON.stringify([{ timestamp: '2026-01-01T00:00:00Z', metrics: { acc: { value: 0.7, higher_is_better: true } } }])
    )
    // Laptop has a newer entry from 2026-01-02
    writeFileSync(
      join(dir, 'route.macbook-pro.json'),
      JSON.stringify([{ timestamp: '2026-01-02T00:00:00Z', metrics: { acc: { value: 0.9, higher_is_better: true } } }])
    )
    const index = buildIndex(dir)
    expect(Object.keys(index)).toEqual(['route'])
    // Should return the laptop's newest entry
    expect(index.route.timestamp).toBe('2026-01-02T00:00:00Z')
    expect(index.route.metrics.acc.value).toBe(0.9)
    expect(index.route.machine).toBe('macbook-pro')
  })
})
