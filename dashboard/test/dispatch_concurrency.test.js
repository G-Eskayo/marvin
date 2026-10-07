import { describe, it, expect } from 'vitest'
import { getConcurrency, setConcurrency } from '../electron/main/dispatch_concurrency.js'
import { describeParallel, COST_NOTE } from '../src/components/ParallelToggle.jsx'

describe('getConcurrency / setConcurrency', () => {
  it('reads the settings the Python side prints', async () => {
    expect(await getConcurrency({ run: async (a) => (a[0] === 'get' ? '{"parallel":false}' : '') })).toEqual({ parallel: false })
  })
  it('saves through the validator and then kicks the code sync', async () => {
    const seen = []
    const out = await setConcurrency({ parallel: true }, { run: async (a) => { seen.push(a); return '{"parallel":true}' }, kick: async () => seen.push('kick') })
    expect(out).toEqual({ parallel: true })
    expect(seen).toEqual([['set', '{"parallel":true}'], 'kick'])
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

describe('describeParallel', () => {
  it('off says one ticket per machine and shows no cost note', () =>
    expect(describeParallel({ parallel: false })).toEqual({ on: false, summary: 'Off: one ticket per machine at a time', note: null }))
  it('on shows the limits and the cost note', () =>
    expect(describeParallel({ parallel: true, max_total: 2, max_per_project: 1 })).toEqual({ on: true, summary: 'On: up to 2 at once, 1 per project', note: COST_NOTE }))
  it('loading is not shown as on', () => expect(describeParallel(null).on).toBe(false))
})
