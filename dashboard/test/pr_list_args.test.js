import { describe, it, expect } from 'vitest'
import { prListArgs } from '../electron/main/mr_repos.js'

describe('prListArgs: what each caller pays GitHub for', () => {
  it('the full listing asks for bodies, files and branch names (the MR list and merge-order check need them)', () => {
    const a = prListArgs('o/r')
    expect(a.slice(0, 5)).toEqual(['pr', 'list', '--repo', 'o/r', '--state'])
    expect(a[a.indexOf('--json') + 1]).toBe('number,title,url,body,files,baseRefName,headRefName,mergeable')
  })
  it('the light listing (the status dot, polled every minute) asks for numbers only', () => {
    const a = prListArgs('o/r', { light: true })
    expect(a[a.indexOf('--json') + 1]).toBe('number,title,url')
    expect(a.join(' ')).not.toMatch(/files|body/)
  })
})

import { createListCache } from '../electron/main/mr_repos.js'
describe('createListCache: the status dot, the MR list and the board must not each hit GitHub', () => {
  const make = () => {
    let calls = { full: 0, light: 0 }
    const fetchers = { full: async () => (calls.full++, ['F']), light: async () => (calls.light++, ['L']) }
    return { calls, cache: createListCache(fetchers, 45_000) }
  }
  it('serves repeat calls within the window from memory', async () => {
    const { calls, cache } = make()
    await cache.get({ light: false, now: 0 }); await cache.get({ light: false, now: 10_000 })
    expect(calls.full).toBe(1)
  })
  it('a fresh full listing also answers a light request (it is a superset)', async () => {
    const { calls, cache } = make()
    await cache.get({ light: false, now: 0 })
    expect(await cache.get({ light: true, now: 5_000 })).toEqual(['F'])
    expect(calls.light).toBe(0)
  })
  it('refetches after the window, and always when fresh is demanded (a merge must not act on stale data)', async () => {
    const { calls, cache } = make()
    await cache.get({ light: false, now: 0 })
    await cache.get({ light: false, now: 50_000 })
    await cache.get({ light: false, now: 51_000, fresh: true })
    expect(calls.full).toBe(3)
  })
  it('a light cache does not answer a full request', async () => {
    const { calls, cache } = make()
    await cache.get({ light: true, now: 0 })
    expect(await cache.get({ light: false, now: 1_000 })).toEqual(['F'])
    expect(calls.full).toBe(1)
  })
})

describe('createListCache.invalidate', () => {
  it('forces the next read to refetch', async () => {
    let n = 0
    const c = createListCache({ full: async () => ++n, light: async () => ++n }, 45_000)
    await c.get({ now: 0 }); c.invalidate(); await c.get({ now: 1 })
    expect(n).toBe(2)
  })
})
