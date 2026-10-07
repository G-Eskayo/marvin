import { describe, it, expect } from 'vitest'
import { getConcurrency, setConcurrency, scanNow } from '../electron/main/dispatch_concurrency.js'
import { describeParallel, COST_NOTE } from '../src/components/ParallelToggle.jsx'

describe('getConcurrency / setConcurrency', () => {
  it('reads the settings the Python side prints', async () => {
    expect(await getConcurrency({ run: async (a) => (a[0] === 'get' ? '{"parallel":false}' : '') })).toEqual({ parallel: false })
  })
  it('saves through the validator and then kicks the code sync', async () => {
    const seen = []
    const out = await setConcurrency({ parallel: false }, { run: async (a) => { seen.push(a); return '{"parallel":false}' }, kick: async (j) => seen.push(`kick ${j}`) })
    expect(out).toEqual({ parallel: false })
    expect(seen).toEqual([['set', '{"parallel":false}'], 'kick code-sync-push'])   // turning it off needs no scan
  })
  it('turning it on also starts a scan now, since the hourly one would make the switch look dead', async () => {
    const kicks = []
    await setConcurrency({ parallel: true }, { run: async () => '{"parallel":true}', kick: async (j) => kicks.push(j) })
    expect(kicks).toEqual(['code-sync-push', 'ticket-pipeline'])
  })
  it('scanNow asks for a scan', async () => {
    const kicks = []
    expect(await scanNow({ kick: async (j) => kicks.push(j) })).toEqual({ requested: true })
    expect(kicks).toEqual(['ticket-pipeline'])
  })
  it('an invalid limit is refused with the reason and the sync is never kicked', async () => {
    let kicked = false
    await expect(setConcurrency({ max_total: 0 }, { run: async () => { throw new Error('max_total must be a whole number from 1 to 8') }, kick: async () => { kicked = true } })).rejects.toThrow(/max_total/)
    expect(kicked).toBe(false)
  })
  it('a failed sync kick never fails the save', async () => {
    expect(await setConcurrency({ parallel: true }, { run: async () => '{"parallel":true}', kick: async () => { throw new Error('nope') } })).toEqual({ parallel: true })
  })
})

describe('describeParallel capacity note', () => {
  const S = { parallel: true, max_total: 4, max_per_project: 3, machine_slots: { 'mac-mini-1': 2, 'macbook-pro-1': 1 } }
  it('says when the machines cap the total you asked for (4 asked, 3 held)', () => {
    const d = describeParallel(S)
    expect(d.summary).toBe('On: up to 3 at once, 3 per project')
    expect(d.capNote).toMatch(/only hold 3 at once.*so 4 runs as 3/)
  })
  it('says plainly when the total fits', () => expect(describeParallel({ ...S, max_total: 2 }).capNote).toMatch(/hold 2 at once/))
})

describe('describeParallel', () => {
  it('off says one ticket per machine and shows no cost note', () =>
    expect(describeParallel({ parallel: false })).toEqual({ on: false, summary: 'Off: one ticket per machine at a time', note: null, capNote: null }))
  it('on shows the limits and the cost note', () =>
    expect(describeParallel({ parallel: true, max_total: 2, max_per_project: 1, machine_slots: { a: 2, b: 1 } })).toMatchObject({ on: true, summary: 'On: up to 2 at once, 1 per project', note: COST_NOTE }))
  it('loading is not shown as on', () => expect(describeParallel(null).on).toBe(false))
})
