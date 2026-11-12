import { describe, it, expect, afterEach, vi } from 'vitest'
import { createServer } from 'http'
import { createStageRelay, createLiveMerges, allowedPeerAddress, cleanStageMessage, stageFanOut } from '../webhook-server/merge_stage_relay.js'
import { createMergeTracker } from '../webhook-server/merge_progress.js'
import { createMergeOps, receiveMergeMessage } from '../electron/main/merge_ops.js'
import { describePrState } from '../src/lib/prState.js'
import { statusFromOp } from '../src/components/MrReview.jsx'

// marvin#231 follow-up: the owner watched a merge the queue started on the Mac mini from the MacBook and saw "Merging"
// with no stage strip. Every stage event now reaches every Mac. These try to break that.
const PR = 'https://github.com/o/r/pull/968'
const quiet = () => {}

// A real merge's events, from the real tracker (the same one runMerge uses), captured as the merge server sends them.
function recordMerge({ fail = false } = {}) {
  const sent = []
  let t = 1000
  const tracker = createMergeTracker({ url: PR, repo: 'o/r', machineId: 'mac-mini-1', log: quiet, now: () => (t += 1000), emit: (event, progress) => sent.push({ url: PR, event, progress }) })
  tracker.start(0)
  tracker.progress('fetching', 'running')
  tracker.progress('fetching', 'done', { gated: true })
  tracker.progress('rebasing', 'running')
  tracker.progress('installing', 'running')
  tracker.progress('tests', 'running', { count: { done: 3, total: 10 } })
  if (fail) tracker.fail({ code: 'GATE_TESTS_FAILED', message: 'test_box_trial failed' })
  else {
    tracker.progress('merging', 'running')
    tracker.finish({ merged: true })
  }
  return sent
}

const servers = []
afterEach(async () => { await Promise.all(servers.splice(0).map((s) => new Promise((r) => s.close(() => r())))) })

describe('the relay to the other Macs', () => {
  it('every event goes to every peer, in order, even when the first post is slow', async () => {
    const got = { a: [], b: [] }
    const post = async (url, body) => {
      const host = url.split('//')[1].split(':')[0]
      if (body.event.seq === 1) await new Promise((r) => setTimeout(r, 30))
      got[host].push(body.event.seq)
      return { ok: true }
    }
    const relay = createStageRelay({ peers: () => [{ host: 'a' }, { host: 'b' }], post })
    const msgs = recordMerge()
    const done = msgs.map((m) => relay(m))
    await Promise.all(done)
    expect(got.a).toEqual(msgs.map((m) => m.event.seq))
    expect(got.b).toEqual(got.a)
  })

  it('an offline or asleep peer never slows the merge: relay() returns at once, and the peer goes quiet instead of piling up', async () => {
    let t = 0
    const calls = []
    const post = (url) => { calls.push(url); return new Promise((_, reject) => setTimeout(() => reject(new Error('timed out')), 20)) }
    const relay = createStageRelay({ peers: () => [{ host: 'asleep' }], post, now: () => t, quietMs: 60_000 })
    const msgs = recordMerge()
    const t0 = Date.now()
    const pending = msgs.map((m) => relay(m))   // what emit does: never awaited
    expect(Date.now() - t0).toBeLessThan(15)
    await Promise.all(pending)
    expect(calls).toHaveLength(1)               // the first failed; the rest were dropped, not queued behind it
    t = 61_000
    await relay(msgs[0])
    expect(calls).toHaveLength(2)               // after the quiet time the next event tries again
  })

  it('a peer list that throws, no peers, or a junk message: nothing sent, nothing thrown', async () => {
    const post = () => { throw new Error('must not post') }
    await createStageRelay({ peers: () => { throw new Error('no registry') }, post })(recordMerge()[0])
    await createStageRelay({ peers: () => [], post })(recordMerge()[0])
    await createStageRelay({ peers: () => [{ host: 'a' }], post })({ url: 'http://evil/pull/1', event: {} })
  })

  it('the fan-out (local dashboard, peers, live record) survives every part failing', () => {
    const live = createLiveMerges()
    const emit = stageFanOut({ url: PR, live, local: () => { throw new Error('no dashboard') }, relay: () => Promise.reject(new Error('down')) })
    for (const m of recordMerge()) emit(m.event, m.progress)
    expect(live.get(PR).progress.outcome).toBe('merged')
  })

  it('a merge started from the phone (no Approve stream at all) reaches this Mac and the peers the same way', () => {
    const local = []
    const relayed = []
    const emit = stageFanOut({ url: PR, local: (m) => local.push(m), relay: (m) => relayed.push(m) })
    // runMerge with by: 'phone' and no reply: the tracker's emit is the fan-out, nothing else.
    const tracker = createMergeTracker({ url: PR, machineId: 'mac-mini-1', log: quiet, emit })
    tracker.start(0)
    tracker.progress('fetching', 'running')
    expect(local.map((m) => m.event.stage)).toEqual(['queued', 'fetching'])
    expect(relayed).toEqual(local)
    expect(relayed[1].progress.stages.queued.state).toBe('done')
  })
})

describe('/merge-stage only takes the owner\'s Macs, and a sane body', () => {
  it('loopback and Tailscale addresses are allowed; the LAN and the internet are not', () => {
    for (const ip of ['127.0.0.1', '::1', '::ffff:127.0.0.1', '100.64.0.1', '100.101.2.3', '100.127.255.254', 'fd7a:115c:a1e0::1']) expect(allowedPeerAddress(ip)).toBe(true)
    for (const ip of ['192.168.1.20', '10.0.0.4', '100.63.0.1', '100.128.0.1', '8.8.8.8', '', null, undefined, 'fd00::1']) expect(allowedPeerAddress(ip)).toBe(false)
  })
  it('a body that is not a PR url with an event is refused; progress without stages is dropped', () => {
    expect(cleanStageMessage(null)).toBeNull()
    expect(cleanStageMessage({ url: 'https://evil.com/x', event: {} })).toBeNull()
    expect(cleanStageMessage({ url: PR })).toBeNull()
    expect(cleanStageMessage({ url: PR, event: { seq: 1 }, progress: 'junk' })).toEqual({ url: PR, event: { seq: 1 }, progress: null })
  })
})

// The receiving side: what the MacBook's dashboard does with what arrives (index.js: event, else adopt the progress).
const receive = (ops, m) => receiveMergeMessage(ops, m)

describe('the card on another Mac', () => {
  it('two Macs fed the same relayed merge show the same strip, and both end merged', () => {
    // Each Mac stamps `at` with its own clock when an event lands, so the two never share it. Tick the clock on
    // every read (CI once crossed a millisecond between the two receives, PR #1264) so this can't pass by timing.
    let t = 1_794_329_773_000
    const clock = vi.spyOn(Date, 'now').mockImplementation(() => ++t)
    try {
      const macbook = createMergeOps()
      const studio = createMergeOps()
      for (const m of recordMerge()) { receive(macbook, m); receive(studio, m) }
      expect(macbook.get(PR).state).toBe('merged')
      const card = ({ at, ...shown }) => shown                   // what the card shows, without this Mac's receipt time
      expect(card(studio.get(PR))).toEqual(card(macbook.get(PR)))
      expect(studio.get(PR).at).toEqual(expect.any(Number))
    } finally { clock.mockRestore() }
  })

  it('events out of order or duplicated end in the same place as in order', () => {
    const msgs = recordMerge()
    const inOrder = createMergeOps()
    for (const m of msgs) receive(inOrder, m)
    const shuffled = createMergeOps()
    for (const m of [msgs[3], msgs[0], msgs[3], msgs[1], msgs[5], msgs[2], msgs[2], ...msgs.slice(4)]) receive(shuffled, m)
    expect(shuffled.get(PR).state).toBe('merged')
    expect(shuffled.get(PR).progress.stages).toEqual(inOrder.get(PR).progress.stages)
  })

  it('a lost event (the Mac slept through Rebasing) is filled in by the next one\'s progress', () => {
    const msgs = recordMerge()
    const ops = createMergeOps()
    receive(ops, msgs[0])
    receive(ops, msgs[5])                                         // tests running; 1..4 never arrived
    const op = ops.get(PR)
    expect(op.state).toBe('merging')
    expect(op.progress.stages.rebasing.state).toBe('done')
    expect(op.progress.stages.tests).toMatchObject({ state: 'running', count: { done: 3, total: 10 } })
  })

  it('the app starting mid-merge catches up from GET /merge-progress, and later events carry on from there', () => {
    const msgs = recordMerge()
    const live = createLiveMerges()
    for (const m of msgs.slice(0, 6)) live.update(PR, m.progress, 'mac-mini-1')
    expect(live.running().map((x) => x.url)).toEqual([PR])
    const ops = createMergeOps()                                   // a fresh app: no op at all
    ops.adopt(PR, live.get(PR).progress)
    expect(statusFromOp(ops.get(PR))).toMatchObject({ status: 'approving' })
    for (const m of msgs.slice(6)) receive(ops, m)
    expect(ops.get(PR).state).toBe('merged')
    // Reading it again changes nothing (same attempt, not ahead).
    expect(ops.adopt(PR, live.get(PR).progress)).toBeNull()
  })

  it('a stale snapshot never rolls a card back, and a finished attempt\'s straggler never restarts it', () => {
    const msgs = recordMerge()
    const ops = createMergeOps()
    for (const m of msgs) receive(ops, m)
    expect(ops.adopt(PR, msgs[2].progress)).toBeNull()
    expect(ops.get(PR).state).toBe('merged')
    expect(ops.adopt(PR, { junk: true })).toBeNull()
    expect(ops.adopt(PR, null)).toBeNull()
  })

  it('a failure mid-pipeline: the card shows the failed stage and leaves the queue state', () => {
    const ops = createMergeOps()
    for (const m of recordMerge({ fail: true })) receive(ops, m)
    const op = ops.get(PR)
    expect(op.state).toBe('error')
    expect(op.progress.stages.tests.state).toBe('failed')
    const v = statusFromOp(op)
    // The list may still say queued until it refreshes: the failure wins.
    const card = describePrState({ checks: { state: 'passing', failing: [], pending: [] }, mergeQueue: { queued: true, state: 'running', reason: 'merging now' } }, v)
    expect(card).toMatchObject({ kind: 'error', headline: 'The last merge attempt failed' })
    expect(card.detail).toMatch(/GATE_TESTS_FAILED/)
  })

  it('end to end over HTTP: the merge server posts, the peer webhook hands it to its dashboard', async () => {
    const ops = createMergeOps()
    const peer = createServer((req, res) => {
      let b = ''
      req.on('data', (c) => (b += c))
      req.on('end', () => {
        if (req.url !== '/merge-stage' || !allowedPeerAddress(req.socket.remoteAddress)) { res.writeHead(403).end(); return }
        const msg = cleanStageMessage(JSON.parse(b))
        if (msg) receive(ops, msg)
        res.writeHead(msg ? 200 : 400).end()
      })
    })
    servers.push(peer)
    const port = await new Promise((r) => peer.listen(0, '127.0.0.1', () => r(peer.address().port)))
    const post = (url, body, { timeoutMs }) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(timeoutMs) })
    const relay = createStageRelay({ peers: () => [{ host: '127.0.0.1' }], post, port })
    await Promise.all(recordMerge().map((m) => relay(m)))
    expect(ops.get(PR).state).toBe('merged')
  })
})

describe('one card, both states', () => {
  const pr = { checks: { state: 'passing', failing: [], pending: [] }, mergeQueue: { queued: true, state: 'queued', reason: 'queued · 2nd · starts after #971' } }
  it('waiting: "Approved: in the merge queue"; its turn comes (the first relayed event): the merging card, with the strip', () => {
    expect(describePrState(pr, { status: 'idle' })).toMatchObject({ kind: 'in-queue', headline: 'Approved: in the merge queue' })
    const ops = createMergeOps()
    receive(ops, recordMerge()[1])
    const v = statusFromOp(ops.get(PR))
    expect(v.progress.stages.fetching.state).toBe('running')
    expect(describePrState(pr, v)).toMatchObject({ kind: 'merging', headline: 'Merging…', approve: 'hidden' })
  })
})
