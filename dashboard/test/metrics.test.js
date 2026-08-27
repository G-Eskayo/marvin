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

  it('returns the full snapshot list for an existing subsystem', () => {
    const snapshots = [
      { timestamp: '2026-01-01T00:00:00Z', metrics: { accuracy: { value: 0.8, higher_is_better: true } } },
      { timestamp: '2026-01-02T00:00:00Z', metrics: { accuracy: { value: 0.9, higher_is_better: true } } }
    ]
    writeFileSync(join(dir, 'route.json'), JSON.stringify(snapshots))
    expect(readHistory('route', dir)).toEqual(snapshots)
  })

  it('returns an empty list instead of throwing on corrupt JSON', () => {
    writeFileSync(join(dir, 'broken.json'), '{not valid json')
    expect(readHistory('broken', dir)).toEqual([])
  })

  it('returns an empty list if the JSON is valid but not an array', () => {
    writeFileSync(join(dir, 'wrongshape.json'), '{"oops": true}')
    expect(readHistory('wrongshape', dir)).toEqual([])
  })
})

describe('latest', () => {
  it('returns null when there is no history', () => {
    expect(latest('missing', dir)).toBeNull()
  })

  it('returns the last snapshot, not the first', () => {
    const snapshots = [
      { timestamp: '2026-01-01T00:00:00Z', metrics: { x: { value: 1, higher_is_better: true } } },
      { timestamp: '2026-01-02T00:00:00Z', metrics: { x: { value: 2, higher_is_better: true } } }
    ]
    writeFileSync(join(dir, 'route.json'), JSON.stringify(snapshots))
    expect(latest('route', dir)).toEqual(snapshots[1])
  })
})

describe('buildIndex', () => {
  it('returns an empty object when no subsystems exist', () => {
    expect(buildIndex(join(dir, 'nonexistent'))).toEqual({})
  })

  it('maps each subsystem to its latest snapshot, skipping empty ones', () => {
    writeFileSync(
      join(dir, 'route.json'),
      JSON.stringify([{ timestamp: 't1', metrics: { acc: { value: 1, higher_is_better: true } } }])
    )
    writeFileSync(join(dir, 'empty.json'), '[]')
    const index = buildIndex(dir)
    expect(Object.keys(index)).toEqual(['route'])
    expect(index.route.metrics.acc.value).toBe(1)
  })
})
