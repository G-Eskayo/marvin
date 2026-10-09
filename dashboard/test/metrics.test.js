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

  it('returns sorted subsystem names from legacy .json files, ignoring others', () => {
    writeFileSync(join(dir, 'zeta.json'), '[]')
    writeFileSync(join(dir, 'alpha.json'), '[]')
    writeFileSync(join(dir, 'index.md'), '# not a subsystem')
    expect(listSubsystems(dir)).toEqual(['alpha', 'zeta'])
  })

  it('groups per-machine files by subsystem', () => {
    writeFileSync(join(dir, 'route.mac-mini.json'), '[]')
    writeFileSync(join(dir, 'route.macbook-pro.json'), '[]')
    writeFileSync(join(dir, 'qa.mac-mini.json'), '[]')
    expect(listSubsystems(dir)).toEqual(['qa', 'route'])
  })

  it('merges legacy and per-machine files for the same subsystem', () => {
    writeFileSync(join(dir, 'route.json'), '[]')  // legacy
    writeFileSync(join(dir, 'route.mac-mini.json'), '[]')  // per-machine
    expect(listSubsystems(dir)).toEqual(['route'])
  })
})

describe('readHistory', () => {
  it('returns an empty list when the subsystem file does not exist', () => {
    expect(readHistory('missing', dir)).toEqual([])
  })

  it('returns the full snapshot list for a legacy flat file', () => {
    const snapshots = [
      { timestamp: '2026-01-01T00:00:00Z', metrics: { accuracy: { value: 0.8, higher_is_better: true } } },
      { timestamp: '2026-01-02T00:00:00Z', metrics: { accuracy: { value: 0.9, higher_is_better: true } } }
    ]
    writeFileSync(join(dir, 'route.json'), JSON.stringify(snapshots))
    const history = readHistory('route', dir)
    expect(history).toHaveLength(2)
    expect(history[history.length - 1].metrics.accuracy.value).toBe(0.9)  // latest last (sorted asc)
  })

  it('merges per-machine files and sorts by timestamp ascending', () => {
    const miniSnapshots = [
      { timestamp: '2026-01-01T00:00:00Z', metrics: { x: { value: 1, higher_is_better: true } } }
    ]
    const mbpSnapshots = [
      { timestamp: '2026-01-02T00:00:00Z', metrics: { x: { value: 2, higher_is_better: true } } }
    ]
    writeFileSync(join(dir, 'route.mac-mini.json'), JSON.stringify(miniSnapshots))
    writeFileSync(join(dir, 'route.macbook-pro.json'), JSON.stringify(mbpSnapshots))
    const history = readHistory('route', dir)
    expect(history).toHaveLength(2)
    expect(history[0].metrics.x.value).toBe(1)  // Earliest first
    expect(history[1].metrics.x.value).toBe(2)  // MBP timestamp is later
  })

  it('merges legacy file with per-machine files', () => {
    const legacy = [
      { timestamp: '2026-01-01T00:00:00Z', metrics: { x: { value: 1, higher_is_better: true } } }
    ]
    const mini = [
      { timestamp: '2026-01-02T00:00:00Z', metrics: { x: { value: 2, higher_is_better: true } } }
    ]
    writeFileSync(join(dir, 'route.json'), JSON.stringify(legacy))
    writeFileSync(join(dir, 'route.mac-mini.json'), JSON.stringify(mini))
    const history = readHistory('route', dir)
    expect(history).toHaveLength(2)
    expect(history[0].metrics.x.value).toBe(1)  // legacy (earliest)
    expect(history[1].metrics.x.value).toBe(2)  // latest
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

  it('returns the latest snapshot from a legacy file', () => {
    const snapshots = [
      { timestamp: '2026-01-01T00:00:00Z', metrics: { x: { value: 1, higher_is_better: true } } },
      { timestamp: '2026-01-02T00:00:00Z', metrics: { x: { value: 2, higher_is_better: true } } }
    ]
    writeFileSync(join(dir, 'route.json'), JSON.stringify(snapshots))
    const result = latest('route', dir)
    expect(result.metrics.x.value).toBe(2)
  })

  it('returns the latest snapshot across per-machine files', () => {
    const miniSnapshots = [
      { timestamp: '2026-01-01T00:00:00Z', metrics: { x: { value: 1, higher_is_better: true } } }
    ]
    const mbpSnapshots = [
      { timestamp: '2026-01-02T00:00:00Z', metrics: { x: { value: 2, higher_is_better: true } } }
    ]
    writeFileSync(join(dir, 'route.mac-mini.json'), JSON.stringify(miniSnapshots))
    writeFileSync(join(dir, 'route.macbook-pro.json'), JSON.stringify(mbpSnapshots))
    const result = latest('route', dir)
    expect(result.metrics.x.value).toBe(2)
  })
})

describe('buildIndex', () => {
  it('returns an empty object when no subsystems exist', () => {
    expect(buildIndex(join(dir, 'nonexistent'))).toEqual({})
  })

  it('maps each subsystem to its latest snapshot from legacy files, skipping empty ones', () => {
    writeFileSync(
      join(dir, 'route.json'),
      JSON.stringify([{ timestamp: 't1', metrics: { acc: { value: 1, higher_is_better: true } } }])
    )
    writeFileSync(join(dir, 'empty.json'), '[]')
    const index = buildIndex(dir)
    expect(Object.keys(index)).toEqual(['route'])
    expect(index.route.metrics.acc.value).toBe(1)
  })

  it('maps each subsystem to its latest snapshot across per-machine files', () => {
    writeFileSync(
      join(dir, 'route.mac-mini.json'),
      JSON.stringify([{ timestamp: '2026-01-01T00:00:00Z', metrics: { acc: { value: 1, higher_is_better: true } } }])
    )
    writeFileSync(
      join(dir, 'route.macbook-pro.json'),
      JSON.stringify([{ timestamp: '2026-01-02T00:00:00Z', metrics: { acc: { value: 2, higher_is_better: true } } }])
    )
    const index = buildIndex(dir)
    expect(Object.keys(index)).toEqual(['route'])
    expect(index.route.metrics.acc.value).toBe(2)
  })
})
