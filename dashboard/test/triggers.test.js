import { describe, it, expect, vi } from 'vitest'
import { createTriggerHub, createReconciler } from '../electron/main/triggers.js'

describe('createTriggerHub', () => {
  it('debounces a burst of file events into one emit per topic', () => {
    vi.useFakeTimers()
    const hub = createTriggerHub({ debounceMs: 200 })
    const got = []
    hub.onTrigger((t) => got.push(t))
    hub.emit('activity', 'stages')
    hub.emit('activity', 'stages')
    hub.emit('activity', 'dispatch')
    expect(got).toEqual([])
    vi.advanceTimersByTime(250)
    expect(got).toEqual([{ topic: 'activity', source: 'dispatch' }])
    vi.useRealTimers()
  })

  it('keeps topics independent', () => {
    vi.useFakeTimers()
    const hub = createTriggerHub({ debounceMs: 50 })
    const got = []
    hub.onTrigger((t) => got.push(t.topic))
    hub.emit('activity', 'a')
    hub.emit('mr', 'b')
    vi.advanceTimersByTime(60)
    expect(got.sort()).toEqual(['activity', 'mr'])
    vi.useRealTimers()
  })

  it('reports when a topic last fired', () => {
    vi.useFakeTimers()
    vi.setSystemTime(1000)
    const hub = createTriggerHub({ debounceMs: 10 })
    expect(hub.lastEmitAt('activity')).toBeNull()
    hub.emit('activity', 'x')
    vi.advanceTimersByTime(20)
    expect(hub.lastEmitAt('activity')).toBe(1010)
    vi.useRealTimers()
  })

  it('watches directories and emits only for the named files', () => {
    vi.useFakeTimers()
    const handlers = {}
    const watch = (dir, cb) => {
      handlers[dir] = cb
      return { close() {} }
    }
    const hub = createTriggerHub({ debounceMs: 10, watch })
    const got = []
    hub.onTrigger((t) => got.push(t))
    hub.watchFiles('activity', [{ dir: '/d', match: (n) => n === 'state.json' }])
    handlers['/d']('change', 'other.txt')
    handlers['/d']('change', 'state.json')
    vi.advanceTimersByTime(20)
    expect(got).toEqual([{ topic: 'activity', source: 'file:state.json' }])
    vi.useRealTimers()
  })

  it('survives a missing directory (watch throws) without crashing', () => {
    const hub = createTriggerHub({
      watch: () => {
        throw new Error('ENOENT')
      }
    })
    expect(() => hub.watchFiles('activity', [{ dir: '/nope', match: () => true }])).not.toThrow()
  })
})

describe('createReconciler', () => {
  const setup = (lastEmit = null) => {
    const misses = []
    let now = 10_000
    const rec = createReconciler({ lastEmitAt: () => lastEmit, record: (m) => misses.push(m), now: () => now })
    return { rec, misses, advance: (ms) => (now += ms) }
  }

  it('never reports the first observation (nothing to compare with)', () => {
    const { rec, misses } = setup()
    rec.observe('activity', 'o/r', 'h1', 'poll')
    expect(misses).toEqual([])
  })

  it('reports a poll that finds a change no trigger announced', () => {
    const { rec, misses, advance } = setup(null)
    rec.observe('activity', 'o/r', 'h1', 'poll')
    advance(60_000)
    rec.observe('activity', 'o/r', 'h2', 'poll')
    expect(misses).toHaveLength(1)
    expect(misses[0]).toMatchObject({ topic: 'activity', key: 'o/r' })
  })

  it('does not report when a trigger fired since the last observation', () => {
    const misses = []
    let now = 10_000
    let lastEmit = null
    const rec = createReconciler({ lastEmitAt: () => lastEmit, record: (m) => misses.push(m), now: () => now })
    rec.observe('activity', 'o/r', 'h1', 'poll')
    now = 40_000
    lastEmit = 30_000 // a trigger announced the change...
    now = 70_000
    rec.observe('activity', 'o/r', 'h2', 'poll') // ...so the poll finding it is not a miss
    expect(misses).toEqual([])
  })

  it('does not report unchanged polls, nor changes seen via a trigger', () => {
    const { rec, misses } = setup(null)
    rec.observe('activity', 'o/r', 'h1', 'poll')
    rec.observe('activity', 'o/r', 'h1', 'poll')
    rec.observe('activity', 'o/r', 'h2', 'trigger')
    expect(misses).toEqual([])
  })
})

import { refetchesGithub, repoFromTrigger } from '../electron/main/triggers.js'
describe('refetchesGithub: which triggers mean GitHub\'s data may have changed', () => {
  it('a local file changing (a pipeline stage file, a doc) does not', () => {
    expect(refetchesGithub({ topic: 'activity', source: 'file:clarity-captions-27.json' })).toBe(false)
    expect(refetchesGithub({ topic: 'docs', source: 'file:CONTEXT.md' })).toBe(false)
    expect(refetchesGithub({ topic: 'agents', source: 'file:run.json' })).toBe(false)
  })
  it('a ping from the change watcher or the webhook does', () => {
    expect(refetchesGithub({ topic: 'activity', source: 'ping' })).toBe(true)
    expect(refetchesGithub({ topic: 'activity', source: 'gh-watch:G-Eskayo/clarity-captions' })).toBe(true)
    expect(refetchesGithub({ topic: 'activity' })).toBe(true) // unknown source: be safe and refresh
  })
})

describe('repoFromTrigger: extract the repo from a GitHub trigger', () => {
  it('extracts the repo from a github: source', () => {
    expect(repoFromTrigger({ source: 'github:G-Eskayo/marvin' })).toBe('G-Eskayo/marvin')
    expect(repoFromTrigger({ source: 'github:G-Eskayo/clarity-captions' })).toBe('G-Eskayo/clarity-captions')
  })
  it('returns null for non-GitHub sources (file, poll, ping, unknown)', () => {
    expect(repoFromTrigger({ source: 'file:state.json' })).toBeNull()
    expect(repoFromTrigger({ source: 'poll' })).toBeNull()
    expect(repoFromTrigger({ source: 'ping' })).toBeNull()
    expect(repoFromTrigger({ source: 'unknown' })).toBeNull()
    expect(repoFromTrigger({})).toBeNull()
    expect(repoFromTrigger(null)).toBeNull()
  })
})
