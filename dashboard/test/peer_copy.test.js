// A standby Mac shows the producer's live copy (marvin#1223, Gil 2026-11-09): when this Mac's own copy of a
// primary-made file is past its tolerance, it asks the producer's GET /copy/<name> and shows whichever is newer,
// saying which Mac and how old. Tries to break it: producer asleep, Tailscale down, a reply that isn't a copy, a
// producer copy older than ours, this Mac being the producer, a hostile reply, and a burst of reads (one fetch).
import { describe, it, expect } from 'vitest'
import { mkdtempSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { createPeerCopies } from '../electron/main/peer_copy.js'

const NOW = Date.parse('2026-11-10T12:00:00Z')
const dir = mkdtempSync(join(tmpdir(), 'peer-'))
const local = join(dir, 'health-status.json')
const stamp = (at, host, extra = {}) => ({ host, generated_at: at, tolerance_s: 1200, checks: [], ...extra })

function make({ isProducer = false, fetchCopy, now = () => NOW } = {}) {
  const calls = []
  const peers = createPeerCopies({ isProducer: () => isProducer, producerHost: () => 'mini', now,
    fetchCopy: async (host, name) => { calls.push([host, name]); return fetchCopy ? fetchCopy(host, name) : null } })
  return { peers, calls }
}

describe('peer copies', () => {
  it('a fresh local copy is used without asking anyone', async () => {
    writeFileSync(local, JSON.stringify(stamp('2026-11-10T11:58:00Z', 'macbook-pro-1')))
    const { peers, calls } = make({ fetchCopy: () => stamp('2026-11-10T11:59:00Z', 'mac-mini-1') })
    const c = await peers.read('health-status', local, { defaultToleranceS: 1200 })
    expect(c.from).toBe('local')
    expect(calls).toEqual([])
  })

  it("a stale local copy on the standby shows the producer's live one, and says so", async () => {
    writeFileSync(local, JSON.stringify(stamp('2026-10-29T12:00:00Z', 'macbook-pro-1')))
    const { peers, calls } = make({ fetchCopy: () => stamp('2026-11-10T11:58:00Z', 'mac-mini-1', { overall: 'yellow' }) })
    const c = await peers.read('health-status', local, { defaultToleranceS: 1200 })
    expect(calls).toEqual([['mini', 'health-status']])
    expect(c).toMatchObject({ from: 'producer', host: 'mac-mini-1', ageS: 120, stale: false })
    expect(c.value.overall).toBe('yellow')
  })

  it('the producer asleep or Tailscale down: our own copy, stale, with its age and Mac', async () => {
    writeFileSync(local, JSON.stringify(stamp('2026-10-29T12:00:00Z', 'macbook-pro-1')))
    const { peers } = make({ fetchCopy: () => null })
    const c = await peers.read('health-status', local, { defaultToleranceS: 1200 })
    expect(c).toMatchObject({ from: 'local', host: 'macbook-pro-1', stale: true, producerUnreachable: true })
  })

  it("the producer's copy older than ours: ours, the newer, and which", async () => {
    writeFileSync(local, JSON.stringify(stamp('2026-11-10T11:00:00Z', 'macbook-pro-1')))
    const { peers } = make({ fetchCopy: () => stamp('2026-11-09T11:00:00Z', 'mac-mini-1') })
    const c = await peers.read('health-status', local, { defaultToleranceS: 1200 })
    expect(c.from).toBe('local')
    expect(c.host).toBe('macbook-pro-1')
  })

  it('on the producer itself nothing is fetched, even when stale', async () => {
    writeFileSync(local, JSON.stringify(stamp('2026-10-29T12:00:00Z', 'mac-mini-1')))
    const { peers, calls } = make({ isProducer: true, fetchCopy: () => stamp('2026-11-10T11:58:00Z', 'x') })
    const c = await peers.read('health-status', local, { defaultToleranceS: 1200 })
    expect(calls).toEqual([])
    expect(c).toMatchObject({ from: 'local', stale: true })
  })

  it.each([['an array', [1, 2]], ['a string', '"x"'], ['a copy with no time', { host: 'mini' }], ['null', null]])('a reply that is %s is ignored', async (_n, reply) => {
    writeFileSync(local, JSON.stringify(stamp('2026-10-29T12:00:00Z', 'macbook-pro-1')))
    const { peers } = make({ fetchCopy: () => reply })
    const c = await peers.read('health-status', local, { defaultToleranceS: 1200 })
    expect(c.from).toBe('local')
  })

  it('a burst of reads asks the producer once (read-through cache), and again after the cache ages out', async () => {
    writeFileSync(local, JSON.stringify(stamp('2026-10-29T12:00:00Z', 'macbook-pro-1')))
    let t = NOW
    const { peers, calls } = make({ now: () => t, fetchCopy: () => stamp('2026-11-10T11:58:00Z', 'mac-mini-1') })
    await Promise.all([1, 2, 3, 4, 5].map(() => peers.read('health-status', local, { defaultToleranceS: 1200 })))
    expect(calls.length).toBe(1)
    t += 61_000
    await peers.read('health-status', local, { defaultToleranceS: 1200 })
    expect(calls.length).toBe(2)
  })

  it('no file here and the producer answers: the producer\'s copy', async () => {
    const { peers } = make({ fetchCopy: () => stamp('2026-11-10T11:58:00Z', 'mac-mini-1') })
    const c = await peers.read('ticket-agent-proposals', join(dir, 'none.json'), { defaultToleranceS: 7200 })
    expect(c).toMatchObject({ from: 'producer', host: 'mac-mini-1' })
  })
})
