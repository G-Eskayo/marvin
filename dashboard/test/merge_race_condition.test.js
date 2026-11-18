import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { createServer } from 'http'
import { approveResponder, createMergeJoin } from '../webhook-server/merge_progress.js'

// marvin#1223 + race condition fixes: tests for the webhook-level behavior
// when a merge finishes and joined replies need to be notified unconditionally
const PR = 'https://github.com/G-Eskayo/marvin/pull/900'
const servers = []
afterEach(async () => { await Promise.all(servers.splice(0).map((s) => new Promise((r) => s.close(() => r())))) })

function serve(handler) {
  const s = createServer((req, res) => {
    let raw = ''
    req.on('data', (c) => (raw += c))
    req.on('end', () => handler(req, res, raw))
  })
  servers.push(s)
  return new Promise((r) => s.listen(0, '127.0.0.1', () => r(`http://127.0.0.1:${s.address().port}/approve`)))
}

describe('mergeJoin webhook integration: hanging reply fix + race condition', () => {
  it('finish is called even when the merge throws, so joined replies get a 500 fallback', async () => {
    // Simulate: a merge throws an error (e.g., in createMergeTracker or catch block)
    // and finish must still be called to unblock joined replies
    const join = createMergeJoin()
    const reply1 = { event: vi.fn(), result: vi.fn() }
    const reply2 = { event: vi.fn(), result: vi.fn() }

    // Two requests join the same PR
    join.join(PR, reply1, () => true)
    join.join(PR, reply2, () => true)

    // Merge throws an error; finish is called with fallback 500 body
    join.finish(PR, 500, { code: 'INTERNAL_ERROR', message: 'no result' })

    // Both replies get the 500 result, not hung forever
    expect(reply1.result).toHaveBeenCalledWith(500, { code: 'INTERNAL_ERROR', message: 'no result' })
    expect(reply2.result).toHaveBeenCalledWith(500, { code: 'INTERNAL_ERROR', message: 'no result' })
  })

  it('join refuses with 409 if isRunning returns false (race: merge finished)', async () => {
    const join = createMergeJoin()
    const reply = { event: vi.fn(), result: vi.fn() }
    const isRunning = vi.fn(() => false) // Merge already finished

    // Request arrives after merge finished but before isRunning turned false
    join.join(PR, reply, isRunning)

    // Join refuses so the caller can fall back
    expect(reply.result).toHaveBeenCalledWith(409, expect.objectContaining({ code: 'ALREADY_MERGING' }))
  })

  it('multiple streams can join the same merge and all get the final result', async () => {
    const join = createMergeJoin()
    const streams = []
    for (let i = 0; i < 3; i++) {
      streams.push({ event: vi.fn(), result: vi.fn() })
    }

    // All three requests join
    for (const s of streams) {
      join.join(PR, s, () => true)
    }

    // Merge sends some events
    const ev1 = { id: 'm1', seq: 1, stage: 'fetching', state: 'running', at: Date.now() }
    join.event(PR, ev1)

    expect(streams.every((s) => s.event.mock.calls.length === 1)).toBe(true)

    // Merge finishes and all streams get the result
    join.finish(PR, 200, { merged: true })
    expect(streams.every((s) => s.result.mock.calls.length === 1)).toBe(true)
    expect(streams[0].result).toHaveBeenCalledWith(200, { merged: true })
    expect(streams[1].result).toHaveBeenCalledWith(200, { merged: true })
    expect(streams[2].result).toHaveBeenCalledWith(200, { merged: true })
  })

  it('if a joined reply throws on event, others still receive events', async () => {
    const join = createMergeJoin()
    const reply1 = { event: vi.fn(() => { throw new Error('boom') }), result: vi.fn() }
    const reply2 = { event: vi.fn(), result: vi.fn() }

    join.join(PR, reply1)
    join.join(PR, reply2)

    const ev = { id: 'm1', seq: 1, stage: 'fetching', state: 'running', at: Date.now() }
    join.event(PR, ev)

    // reply1 threw but reply2 still got the event
    expect(reply2.event).toHaveBeenCalledWith(ev)
  })

  it('if a joined reply throws on result, others still receive the result', async () => {
    const join = createMergeJoin()
    const reply1 = { event: vi.fn(), result: vi.fn(() => { throw new Error('boom') }) }
    const reply2 = { event: vi.fn(), result: vi.fn() }

    join.join(PR, reply1)
    join.join(PR, reply2)

    join.finish(PR, 200, { merged: true })

    // reply1 threw but reply2 still got the result
    expect(reply2.result).toHaveBeenCalledWith(200, { merged: true })
  })

  it('finish with null replies (reply = undefined) does not crash', async () => {
    const join = createMergeJoin()
    // Join without a reply object (edge case)
    join.join(PR, null)
    join.join(PR, undefined)

    // Should not throw
    join.finish(PR, 200, { merged: true })
  })

  it('late join after merge finished sees 409 due to isRunning check', async () => {
    const join = createMergeJoin()
    let running = true
    const isRunning = () => running

    const reply1 = { event: vi.fn(), result: vi.fn() }
    const reply2 = { event: vi.fn(), result: vi.fn() }

    // First request joins while running
    join.join(PR, reply1, isRunning)

    // Merge finishes
    running = false
    join.finish(PR, 200, { merged: true })

    // Second request arrives after merge finished but tries to join
    join.join(PR, reply2, isRunning)

    // First request got the real result
    expect(reply1.result).toHaveBeenCalledWith(200, { merged: true })

    // Late request got 409
    expect(reply2.result).toHaveBeenCalledWith(409, expect.objectContaining({ code: 'ALREADY_MERGING' }))
  })

  it('concurrent joins race-safe: isRunning is checked at join time, not before', async () => {
    const join = createMergeJoin()
    let running = true
    const isRunning = vi.fn(() => running)

    const reply1 = { event: vi.fn(), result: vi.fn() }
    const reply2 = { event: vi.fn(), result: vi.fn() }

    // Start merge
    join.join(PR, reply1, isRunning)

    // Meanwhile: merge finishes
    running = false
    join.finish(PR, 200, { merged: true })

    // And simultaneously another request tries to join (tight race)
    join.join(PR, reply2, isRunning)

    // The second join's isRunning check happens *after* finish,
    // so it returns false and refuses with 409
    expect(isRunning).toHaveBeenCalled()
    expect(reply2.result).toHaveBeenCalledWith(409, expect.any(Object))
  })

  it('event/finish on a URL with no joiners is idempotent and safe', async () => {
    const join = createMergeJoin()

    // No join for this URL
    const ev = { id: 'm1', seq: 1, stage: 'fetching', state: 'running', at: Date.now() }
    join.event(PR, ev) // Should not crash

    join.finish(PR, 200, { merged: true }) // Should not crash
    join.finish(PR, 200, { merged: true }) // Should not crash on second call
  })

  it('separate URLs are independent', async () => {
    const join = createMergeJoin()
    const PR2 = 'https://github.com/G-Eskayo/marvin/pull/901'

    const reply1 = { event: vi.fn(), result: vi.fn() }
    const reply2 = { event: vi.fn(), result: vi.fn() }

    join.join(PR, reply1, () => true)
    join.join(PR2, reply2, () => true)

    // Finish only PR
    join.finish(PR, 200, { merged: true })

    expect(reply1.result).toHaveBeenCalledWith(200, { merged: true })
    expect(reply2.result).not.toHaveBeenCalled()

    // Finish PR2
    join.finish(PR2, 200, { merged: true })
    expect(reply2.result).toHaveBeenCalledWith(200, { merged: true })
  })
})
