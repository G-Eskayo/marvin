import { describe, it, expect, afterEach } from 'vitest'
import { createServer } from 'http'
import { approveMrStream, MAX_LINE } from '../electron/main/approve_stream.js'
import { approveResponder, wantsStream } from '../webhook-server/merge_progress.js'
import { createMergeOps } from '../electron/main/merge_ops.js'

// marvin#568: the approve request is the push channel. These run a real HTTP server speaking the webhook's own
// responder (approveResponder), so the client is tested against the real protocol, not a mock of it.
const PR = 'https://github.com/G-Eskayo/marvin/pull/559'
let server
afterEach(() => new Promise((r) => (server ? server.close(() => r()) : r())))

function serve(handler) {
  server = createServer((req, res) => {
    let raw = ''
    req.on('data', (c) => (raw += c))
    req.on('end', () => handler(req, res, raw))
  })
  return new Promise((r) => server.listen(0, '127.0.0.1', () => r(`http://127.0.0.1:${server.address().port}/approve`)))
}
const ev = (seq, stage, state, extra = {}) => ({ id: 'a1', seq, stage, state, at: seq, ...extra })
const tick = () => new Promise((r) => setTimeout(r, 5))

describe('approveMrStream', () => {
  it('asks for the stream, hands each stage event over as it arrives, and resolves with the result', async () => {
    let asked
    const url = await serve(async (req, res, raw) => {
      asked = { accept: req.headers.accept, body: JSON.parse(raw), stream: wantsStream(req.headers.accept) }
      const reply = approveResponder(res, { streaming: asked.stream })
      reply.event(ev(1, 'queued', 'running')); await tick()
      reply.event(ev(2, 'tests', 'running', { count: { done: 3, total: 10, unit: 'files' } })); await tick()
      reply.result(200, { merged: true, reengaged: false, reason: null })
    })
    const seen = []
    const r = await approveMrStream(PR, url, { onEvent: (e) => seen.push(`${e.stage}:${e.state}`) })
    expect(asked).toEqual({ accept: 'application/x-ndjson', body: { pr_url: PR }, stream: true })
    expect(seen).toEqual(['queued:running', 'tests:running'])
    expect(r).toEqual({ merged: true, reengaged: false, reason: null })
  })

  it('a refusal in the result line throws the same described error approveMr does, with the payload', async () => {
    const url = await serve((req, res) => {
      const reply = approveResponder(res, { streaming: true })
      reply.event(ev(1, 'queued', 'running'))
      reply.result(503, { code: 'GATE_INFRA', stage: 'gate', action: 'escalate', message: 'the check did not finish in time', remediation: 'Approve it again.' })
    })
    const err = await approveMrStream(PR, url).catch((e) => e)
    expect(err.message).toBe('GATE_INFRA at gate: the check did not finish in time -- needs you. Approve it again.')
    expect(err.payload.code).toBe('GATE_INFRA')
  })

  it('a send-back is a normal result (merged: false, reengaged: true)', async () => {
    const url = await serve((req, res) => approveResponder(res, { streaming: true }).result(200, { merged: false, reengaged: true, reason: 'tests failed' }))
    expect(await approveMrStream(PR, url)).toMatchObject({ reengaged: true })
  })

  it('webhook restart mid-merge: the stream drops with no result -> interrupted, at once, after the events so far', async () => {
    const url = await serve(async (req, res) => {
      const reply = approveResponder(res, { streaming: true })
      reply.event(ev(1, 'queued', 'running'))
      reply.event(ev(2, 'tests', 'running')); await tick()
      res.socket.destroy() // the process died
    })
    const ops = createMergeOps()
    ops.start(PR, Date.now(), 'aaa')
    const r = await approveMrStream(PR, url, { onEvent: (e) => ops.event(PR, e) })
    expect(r).toEqual({ merged: false, interrupted: true, reason: 'The merge was interrupted when the webhook restarted. Approve again.' })
    const op = ops.interrupt(PR)
    expect(op.state).toBe('interrupted')
    expect(op.progress.stages.tests.state).toBe('failed') // the card shows where it got to, and that it stopped there
  })

  it('a webhook that cannot be reached at all is an error (nothing started), not an interruption', async () => {
    const url = await serve(() => {})
    const port = server.address().port
    await new Promise((r) => server.close(() => r()))
    server = null
    await expect(approveMrStream(PR, `http://127.0.0.1:${port}/approve`)).rejects.toThrow(/ECONNREFUSED/)
  })

  it('an older webhook that answers plain JSON still works, success and refusal', async () => {
    let n = 0
    const url = await serve((req, res) => {
      n += 1
      if (n === 1) res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ merged: true }))
      else res.writeHead(409, { 'Content-Type': 'application/json' }).end(JSON.stringify({ code: 'WRONG_BASE', stage: 'request', action: 'escalate', message: 'targets side' }))
    })
    expect(await approveMrStream(PR, url)).toEqual({ merged: true })
    await expect(approveMrStream(PR, url)).rejects.toThrow(/WRONG_BASE at request: targets side/)
  })

  it('garbled, unknown and oversized lines are skipped; duplicates are passed on (the reducer drops them)', async () => {
    const url = await serve(async (req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/x-ndjson' })
      res.write('{not json\n')
      res.write(JSON.stringify({ type: 'nonsense' }) + '\n')
      res.write(JSON.stringify({ type: 'progress', event: 'str' }) + '\n')
      res.write('x'.repeat(MAX_LINE + 10))
      res.write('\n' + JSON.stringify({ type: 'progress', event: ev(1, 'queued', 'running') }) + '\n')
      res.write(JSON.stringify({ type: 'progress', event: ev(1, 'queued', 'running') }) + '\n')
      res.end(JSON.stringify({ type: 'result', status: 200, body: { merged: true } }) + '\n')
    })
    const seen = []
    const ops = createMergeOps()
    ops.start(PR)
    const pushed = []
    expect(await approveMrStream(PR, url, { onEvent: (e) => { seen.push(e.seq); const op = ops.event(PR, e); if (op) pushed.push(op) } })).toEqual({ merged: true })
    expect(seen).toEqual([1, 1])
    expect(pushed).toHaveLength(1) // the duplicate changed nothing, so nothing was pushed to the card
  })

  it('a listener that throws does not lose the result', async () => {
    const url = await serve((req, res) => {
      const reply = approveResponder(res, { streaming: true })
      reply.event(ev(1, 'queued', 'running'))
      reply.result(200, { merged: true })
    })
    expect(await approveMrStream(PR, url, { onEvent: () => { throw new Error('renderer gone') } })).toEqual({ merged: true })
  })

  it('a junk webhook URL is refused before anything is sent', async () => {
    await expect(approveMrStream(PR, 'not a url')).rejects.toThrow(/Not a webhook URL/)
  })
})

describe('approveResponder (the webhook side)', () => {
  it('without the stream header the answer is the plain JSON response, as before (phone backend, auto-merge)', async () => {
    expect(wantsStream(undefined)).toBe(false)
    expect(wantsStream('application/json')).toBe(false)
    expect(wantsStream('application/x-ndjson, */*')).toBe(true)
    const url = await serve((req, res) => {
      const reply = approveResponder(res, { streaming: wantsStream(req.headers.accept) })
      reply.event(ev(1, 'queued', 'running')) // dropped: nobody asked for a stream
      reply.result(200, { merged: true })
    })
    const res = await fetch(url, { method: 'POST', body: '{}' })
    expect(res.headers.get('content-type')).toBe('application/json')
    expect(await res.json()).toEqual({ merged: true })
  })

  it('writing after the reader went away is harmless', async () => {
    let wrote = null
    const url = await serve(async (req, res) => {
      const reply = approveResponder(res, { streaming: true })
      req.socket.destroy()
      await tick()
      try { reply.event(ev(1, 'queued', 'running')); reply.result(200, { merged: true }); wrote = 'ok' } catch (e) { wrote = e }
    })
    await approveMrStream(PR, url).catch(() => {})
    await tick(); await tick()
    expect(wrote).toBe('ok')
  })
})
