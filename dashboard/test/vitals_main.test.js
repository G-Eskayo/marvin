import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync, mkdirSync, rmSync, symlinkSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { MAP_SCHEME, mapFileFor, createMapHandler, MAP_CSP } from '../electron/main/map_frame.js'
import { readPlanMeter } from '../electron/main/plan_meter.js'

// Vitals mock-up (marvin#873): the live map is drawn behind the tab from brain-map/, served by one scheme that can
// only ever return the map's own page, its vendor script and the two live files it reads. Nothing else on disk.
describe('map frame: which files the scheme serves', () => {
  const dir = '/maps/brain-map'
  it('the page, its vendor scripts and its two live files', () => {
    expect(mapFileFor(`${MAP_SCHEME}://map/index.html`, dir)).toEqual({ file: '/maps/brain-map/index.html', type: 'text/html; charset=utf-8' })
    expect(mapFileFor(`${MAP_SCHEME}://map/vendor/motion.12.42.2.js`, dir).file).toBe('/maps/brain-map/vendor/motion.12.42.2.js')
    expect(mapFileFor(`${MAP_SCHEME}://map/work.json?_=123`, dir).file).toBe('/maps/brain-map/work.json')
    expect(mapFileFor(`${MAP_SCHEME}://map/activity.jsonl?_=1`, dir).file).toBe('/maps/brain-map/activity.jsonl')
    expect(mapFileFor(`${MAP_SCHEME}://map/`, dir).file).toBe('/maps/brain-map/index.html')
  })
  it('refuses everything else: traversal, encoded traversal, other files, other hosts, junk', () => {
    for (const u of ['../../etc/passwd', '..%2F..%2Fetc%2Fpasswd', 'vendor/../../x.js', 'vendor/%2e%2e/%2e%2e/x.js', 'tree-data.json', 'enrichment.json',
      'generate.py', 'vendor/evil.html', 'vendor/sub/x.js', 'INDEX.HTML', 'index.html%00.js']) {
      expect(mapFileFor(`${MAP_SCHEME}://map/${u}`, dir), u).toBe(null)
    }
    expect(mapFileFor(`${MAP_SCHEME}://other/index.html`, dir)).toBe(null)
    expect(mapFileFor('file:///maps/brain-map/index.html', dir)).toBe(null)
    expect(mapFileFor('not a url', dir)).toBe(null)
    expect(mapFileFor(null, dir)).toBe(null)
  })
})

describe('map frame: the handler', () => {
  it('serves the page with its own CSP, 404s the rest, and a missing file is a 404 not a crash', async () => {
    const root = mkdtempSync(path.join(tmpdir(), 'map-frame-'))
    try {
      mkdirSync(path.join(root, 'vendor'))
      writeFileSync(path.join(root, 'index.html'), '<p>map</p>')
      writeFileSync(path.join(root, 'secret.txt'), 'no')
      const handle = createMapHandler({ dir: root })
      const ok = await handle({ url: `${MAP_SCHEME}://map/index.html` })
      expect(ok.status).toBe(200)
      expect(await ok.text()).toBe('<p>map</p>')
      expect(ok.headers.get('content-security-policy')).toBe(MAP_CSP)
      expect(ok.headers.get('cache-control')).toBe('no-store')
      expect((await handle({ url: `${MAP_SCHEME}://map/secret.txt` })).status).toBe(404)
      expect((await handle({ url: `${MAP_SCHEME}://map/work.json` })).status).toBe(404)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
  it('a symlinked file pointing outside the map folder is refused', async () => {
    const root = mkdtempSync(path.join(tmpdir(), 'map-frame-'))
    const outside = mkdtempSync(path.join(tmpdir(), 'map-outside-'))
    try {
      writeFileSync(path.join(outside, 'x.json'), '{"secret":1}')
      symlinkSync(path.join(outside, 'x.json'), path.join(root, 'work.json'))
      const handle = createMapHandler({ dir: root })
      expect((await handle({ url: `${MAP_SCHEME}://map/work.json` })).status).toBe(404)
    } finally {
      rmSync(root, { recursive: true, force: true })
      rmSync(outside, { recursive: true, force: true })
    }
  })
  it('the map page may run its own scripts and read only its own scheme', () => {
    expect(MAP_CSP).toMatch(/default-src 'none'/)
    expect(MAP_CSP).toMatch(new RegExp(`connect-src ${MAP_SCHEME}:`))
    expect(MAP_CSP).not.toMatch(/https?:/)
  })
})

// The verdict line's budget: the plan's own meter, the last row of ~/.claude/logs/plan-usage.jsonl (lib/plan_usage.py).
describe('readPlanMeter', () => {
  const withFile = (text, fn) => {
    const root = mkdtempSync(path.join(tmpdir(), 'plan-meter-'))
    const file = path.join(root, 'plan-usage.jsonl')
    if (text != null) writeFileSync(file, text)
    try { return fn(file) } finally { rmSync(root, { recursive: true, force: true }) }
  }
  const row = (pct) => JSON.stringify({ ts: '2026-11-12T17:01:25Z', machine: 'macbook-pro-1', five_hour: { used_percentage: pct, resets_at: 1794503400 }, seven_day: null, limit_hit: [] })
  it('the last good row', () => withFile([row(10), row(30), ''].join('\n'), (f) => expect(readPlanMeter(f).five_hour.used_percentage).toBe(30)))
  it('skips a torn last line (a write in progress)', () => withFile(`${row(10)}\n${row(20)}\n{"ts": "2026-11-1`, (f) => expect(readPlanMeter(f).five_hour.used_percentage).toBe(20)))
  it('missing, empty or all junk: null (not enough data, never 0%)', () => {
    withFile(null, (f) => expect(readPlanMeter(f)).toBe(null))
    withFile('', (f) => expect(readPlanMeter(f)).toBe(null))
    withFile('nope\n[1,2]\n"x"\n', (f) => expect(readPlanMeter(f)).toBe(null))
  })
  it('reads only the end of a big file', () => {
    const big = Array.from({ length: 20_000 }, (_, i) => row(i % 100)).join('\n')
    withFile(big, (f) => expect(readPlanMeter(f).five_hour.used_percentage).toBe(19_999 % 100))
  })
})
