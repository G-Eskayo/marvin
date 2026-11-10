// The JS twin of lib/stamped.py (marvin#1223): the same shared cases, so the two readers can't drift.
import { describe as group, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync, utimesSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { readStamped, fromData, describeCopy, newerCopy, producerOf } from '../electron/main/stamped.js'
import cases from './fixtures/stamped_cases.json'

const NOW = Date.parse(cases.now)
const dir = mkdtempSync(join(tmpdir(), 'stamped-'))

group('stamped.js shared cases', () => {
  for (const c of cases.cases) {
    it(c.name, () => {
      const p = join(dir, `${c.name.replace(/\W+/g, '_')}.json`)
      writeFileSync(p, JSON.stringify(c.data))
      if (c.mtime) utimesSync(p, c.mtime, c.mtime)
      const got = readStamped(p, { now: NOW, defaultToleranceS: c.default_tolerance_s ?? 600 })
      for (const [k, v] of Object.entries(c.expect)) {
        if (k === 'value_x') expect(got.value.x).toBe(v)
        else expect(got[{ age_s: 'ageS' }[k] || k]).toBe(v)
      }
    })
  }
})

group('stamped.js edges', () => {
  it('no file, half a file, or not an object is missing and stale, never a throw', () => {
    expect(readStamped(join(dir, 'nope.json'), { now: NOW })).toMatchObject({ missing: true, stale: true, value: null })
    for (const text of ['{half', '', '[1]', 'null']) {
      const p = join(dir, 'bad.json')
      writeFileSync(p, text)
      expect(readStamped(p, { now: NOW })).toMatchObject({ missing: true, stale: true, value: null })
    }
  })

  it('names the producer by hardware_uuid after a rename, and reads like a person', () => {
    const registry = { 'mac-mini-1': { label: 'Mac mini', hardware_uuid: 'U-MINI' } }
    const c = fromData({ host: 'old-name', hardware_uuid: 'u-mini', generated_at: '2026-11-10T11:58:00Z', tolerance_s: 600 }, { now: NOW })
    expect(producerOf(c, registry)).toBe('mac-mini-1')
    expect(describeCopy(c, registry)).toBe('Mac mini, as of 2 min ago')
    const old = fromData({ generated_at: '2026-10-30T12:00:00Z' }, { now: NOW, defaultToleranceS: 1200 })
    expect(describeCopy(old, {}, { thisMac: 'macbook-pro-1' })).toBe('this Mac (unstamped), as of 11 days ago · stale')
  })

  it('newer picks the fresher copy either way round', () => {
    const local = fromData({ host: 'a', generated_at: '2026-10-30T12:00:00Z', tolerance_s: 1200 }, { now: NOW })
    const peer = fromData({ host: 'b', generated_at: '2026-11-10T11:58:00Z', tolerance_s: 1200 }, { now: NOW })
    expect(newerCopy(local, peer)).toBe(peer)
    expect(newerCopy(peer, local)).toBe(peer)
    const missing = fromData(null, { now: NOW })
    expect(newerCopy(missing, local)).toBe(local)
  })
})
