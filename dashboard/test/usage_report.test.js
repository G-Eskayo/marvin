import { describe, it, expect, vi } from 'vitest'
import { getUsageReport, clearUsageCache } from '../electron/main/usage_report.js'

const doc = { generated_at: '2026-10-06T12:00:00Z', machines: [{ machine: 'mac-mini-1', this: true }] }

describe('getUsageReport', () => {
  it('parses what lib/usage_report.py prints', async () => {
    clearUsageCache()
    const run = vi.fn(async () => JSON.stringify(doc))
    expect(await getUsageReport({ run, now: 1000 })).toEqual({ report: doc, error: null })
  })

  it('answers repeat calls from the cache, and shares one scan between simultaneous callers', async () => {
    clearUsageCache()
    let release
    const run = vi.fn(() => new Promise((r) => { release = () => r(JSON.stringify(doc)) }))
    const a = getUsageReport({ run, now: 1000 })
    const b = getUsageReport({ run, now: 1001 })
    release()
    await Promise.all([a, b])
    expect(run).toHaveBeenCalledTimes(1)
    await getUsageReport({ run, now: 1000 + 30_000 })
    expect(run).toHaveBeenCalledTimes(1)
    release = null
    const run2 = vi.fn(async () => JSON.stringify(doc))
    await getUsageReport({ run: run2, now: 1000 + 120_000 })
    expect(run2).toHaveBeenCalledTimes(1)
  })

  it('reports a failure instead of throwing, and keeps the last good report', async () => {
    clearUsageCache()
    await getUsageReport({ run: async () => JSON.stringify(doc), now: 1000 })
    const r = await getUsageReport({ run: async () => { throw new Error('boom') }, now: 1000 + 120_000 })
    expect(r.error).toMatch(/boom/)
    expect(r.report).toEqual(doc)
  })

  it('a bad payload is an error, not a crash', async () => {
    clearUsageCache()
    const r = await getUsageReport({ run: async () => 'not json', now: 1000 })
    expect(r.report).toBeNull()
    expect(r.error).toMatch(/usage report/i)
  })
})
