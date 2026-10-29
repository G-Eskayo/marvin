import { describe, it, expect, afterEach, beforeEach } from 'vitest'
import { createServer } from 'http'
import { EventEmitter } from 'events'
import { mkdtempSync, rmSync, readFileSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { approveMrStream } from '../electron/main/approve_stream.js'
import { approveResponder } from '../webhook-server/merge_progress.js'
import { createMergeOps } from '../electron/main/merge_ops.js'
import { mergeMachines, approveOnAnyMachine, failoverNotice, noMachineReason } from '../electron/main/merge_failover.js'
import { createApprovalLedger } from '../electron/main/approval_ledger.js'
import { createApprovalRetry } from '../electron/main/approval_retry.js'
import { createApproveFlow } from '../electron/main/approve_flow.js'

// marvin#762: the Mac mini down must not mean every approval fails. These run real HTTP servers (the webhook's own
// responder) and real closed ports, so "unreachable" is the operating system's answer, not a mocked error.
const PR = 'https://github.com/G-Eskayo/marvin/pull/900'
const PR2 = 'https://github.com/G-Eskayo/marvin/pull/901'
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
// A port nothing listens on: bind one, then close it, so connecting is refused (the Mini's webhook stopped).
async function closedPortUrl() {
  const s = createServer()
  await new Promise((r) => s.listen(0, '127.0.0.1', r))
  const port = s.address().port
  await new Promise((r) => s.close(r))
  return `http://127.0.0.1:${port}/approve`
}
const merging = (calls, body = { merged: true, reengaged: false, reason: null }) => (req, res, raw) => {
  calls.push(JSON.parse(raw).pr_url)
  const reply = approveResponder(res, { streaming: true })
  reply.event({ id: 'x', seq: 1, stage: 'queued', state: 'running', at: 1 })
  reply.result(200, body)
}
const MINI = (url) => ({ id: 'mac-mini-1', label: 'Mac mini', url, here: false })
const BOOK = (url) => ({ id: 'macbook-pro-1', label: 'MacBook Pro', url, here: true })
const send = (prUrl, url) => approveMrStream(prUrl, url, { connectTimeoutMs: 300 })

describe('approveMrStream: telling "could not reach it" from "it answered"', () => {
  it('a refused connection (webhook stopped) is marked unreachable: nothing was sent', async () => {
    const err = await approveMrStream(PR, await closedPortUrl()).catch((e) => e)
    expect(err.unreachable).toBe(true)
    expect(err.code).toBe('ECONNREFUSED')
  })

  it('no connection within the time limit (machine asleep or off the network) is unreachable, not a 75 s hang', async () => {
    // A request that never gets a connected socket: what a powered-off Mac on Tailscale looks like.
    const request = () => {
      const req = new EventEmitter()
      req.end = () => {}
      req.destroy = (e) => req.emit('error', e)
      return req
    }
    const started = Date.now()
    const err = await approveMrStream(PR, 'http://100.82.55.107:7878/approve', { request, connectTimeoutMs: 50 }).catch((e) => e)
    expect(err.unreachable).toBe(true)
    expect(err.code).toBe('ETIMEDOUT')
    expect(Date.now() - started).toBeLessThan(1000)
  })

  it('a webhook that answers with a refusal is NOT unreachable (never fail over a real answer)', async () => {
    const url = await serve((req, res) => approveResponder(res, { streaming: true }).result(409, { code: 'NOT_READY', stage: 'gate', action: 'escalate', message: 'no' }))
    const err = await approveMrStream(PR, url, { connectTimeoutMs: 300 }).catch((e) => e)
    expect(err.unreachable).toBeFalsy()
  })

  it('a webhook that accepted the request and then went away is interrupted, not unreachable (it may be merging)', async () => {
    const url = await serve((req, res) => { approveResponder(res, { streaming: true }).event({ id: 'x', seq: 1, stage: 'queued', state: 'running', at: 1 }); setTimeout(() => res.socket.destroy(), 10) })
    const r = await approveMrStream(PR, url, { connectTimeoutMs: 300 })
    expect(r.interrupted).toBe(true)
  })
})

describe('mergeMachines: where an approval can go', () => {
  it('a MacBook: the Mini first, then this MacBook\'s own webhook', () => {
    const m = mergeMachines({ primaryUrl: 'http://gils-mac-mini:7878/approve', primaryId: 'mac-mini-1', localId: 'macbook-pro-1' })
    expect(m.map((x) => [x.label, x.url, x.here])).toEqual([
      ['Mac mini', 'http://gils-mac-mini:7878/approve', false],
      ['MacBook Pro', 'http://localhost:7878/approve', true]
    ])
  })

  it('the Mini itself: only itself (the primary is already local, there is nowhere else to go)', () => {
    const m = mergeMachines({ primaryUrl: 'http://localhost:7878/approve', primaryId: 'mac-mini-1', localId: 'mac-mini-1' })
    expect(m).toHaveLength(1)
    expect(m[0].here).toBe(true)
  })

  it('an explicit webhook URL (MARVIN_MR_WEBHOOK_URL: evidence captures, n8n) is used alone, never failed over', () => {
    const m = mergeMachines({ primaryUrl: 'http://127.0.0.1:5555/approve', explicit: true, primaryId: 'mac-mini-1', localId: 'macbook-pro-1' })
    expect(m.map((x) => x.url)).toEqual(['http://127.0.0.1:5555/approve'])
  })

  it('an explicit webhook URL with an explicit local one (MARVIN_MR_LOCAL_WEBHOOK_URL: the failover evidence capture) fails over between the two', () => {
    const m = mergeMachines({ primaryUrl: 'http://127.0.0.1:5555/approve', explicit: true, localUrl: 'http://127.0.0.1:6666/approve', localExplicit: true, primaryId: 'mac-mini-1', localId: 'macbook-pro-1' })
    expect(m.map((x) => [x.label, x.url])).toEqual([['Mac mini', 'http://127.0.0.1:5555/approve'], ['MacBook Pro', 'http://127.0.0.1:6666/approve']])
  })

  it('unknown machines still get plain names, never a bare id or undefined', () => {
    const m = mergeMachines({ primaryUrl: 'http://gils-mac-mini:7878/approve', primaryId: null, localId: null })
    expect(m.map((x) => x.label)).toEqual(['Mac mini', 'this Mac'])
  })
})

describe('approveOnAnyMachine (acceptance: the Mini unreachable means a local merge)', () => {
  it('the Mini refuses connections: merges on this MacBook and says so in plain words, once', async () => {
    const calls = []
    const local = await serve(merging(calls))
    const notices = []
    const r = await approveOnAnyMachine(PR, [MINI(await closedPortUrl()), BOOK(local)], { send, onSwitch: (n) => notices.push(n) })
    expect(r.result.merged).toBe(true)
    expect(r.machine.label).toBe('MacBook Pro')
    expect(calls).toEqual([PR])
    expect(notices).toEqual(['The Mac mini is offline, merging on this MacBook Pro instead.'])
  })

  it('the Mini up: it merges, the MacBook is never asked, no notice', async () => {
    const miniCalls = [], bookCalls = []
    const mini = await serve(merging(miniCalls))
    const book = await serve(merging(bookCalls))
    const notices = []
    const r = await approveOnAnyMachine(PR, [MINI(mini), BOOK(book)], { send, onSwitch: (n) => notices.push(n) })
    expect(r.machine.label).toBe('Mac mini')
    expect([miniCalls, bookCalls, notices]).toEqual([[PR], [], []])
  })

  it('the Mini answers with a refusal (tests failed, low disk): that answer stands; never retried on the MacBook', async () => {
    const bookCalls = []
    const mini = await serve((req, res) => approveResponder(res, { streaming: true }).result(503, { code: 'GATE_INFRA', stage: 'gate', action: 'escalate', message: 'disk full' }))
    const book = await serve(merging(bookCalls))
    const err = await approveOnAnyMachine(PR, [MINI(mini), BOOK(book)], { send }).catch((e) => e)
    expect(err.message).toMatch(/GATE_INFRA/)
    expect(err.noMachine).toBeFalsy()
    expect(bookCalls).toEqual([])
  })

  it('acceptance: both down -> one plain error saying why for each, marked noMachine (to be queued), no bare timeout', async () => {
    const err = await approveOnAnyMachine(PR, [MINI(await closedPortUrl()), BOOK(await closedPortUrl())], { send }).catch((e) => e)
    expect(err.noMachine).toBe(true)
    expect(err.message).toBe("Neither Mac can merge right now: the Mac mini is offline, and this MacBook Pro's merge service isn't running. Your approval is saved and will merge by itself when one comes back.")
    expect(err.message).not.toMatch(/ETIMEDOUT|ECONNREFUSED/)
  })

  it('only the Mini is configured and it is down: still a plain queued message', async () => {
    expect(noMachineReason([{ machine: MINI('x'), code: 'ETIMEDOUT' }])).toBe('The Mac mini is offline, so nothing can merge right now. Your approval is saved and will merge by itself when it comes back.')
  })

  it('the notice reads the same for any pair of machines', () => {
    expect(failoverNotice(MINI(''), BOOK(''))).toBe('The Mac mini is offline, merging on this MacBook Pro instead.')
  })
})

describe('approval ledger: every click is written down before it is sent', () => {
  let dir, file
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'ledger-')); file = path.join(dir, 'approvals.json') })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))

  it('record -> sending, conclude -> outcome; it survives a restart (a new ledger on the same file)', () => {
    const a = createApprovalLedger(file, { now: () => 1000 })
    a.record(PR, { number: 900, head: 'abc' })
    expect(JSON.parse(readFileSync(file, 'utf8')).approvals[0]).toMatchObject({ url: PR, number: 900, head: 'abc', clickedAt: 1000, outcome: 'sending' })
    a.conclude(PR, 'queued', { reason: 'both down' })
    const b = createApprovalLedger(file)
    expect(b.get(PR)).toMatchObject({ outcome: 'queued', reason: 'both down', clickedAt: 1000 })
    expect(b.waiting().map((x) => x.url)).toEqual([PR])
  })

  it('only approvals no machine took are waiting: a refusal or a merge is not retried', () => {
    const a = createApprovalLedger(file)
    a.record(PR); a.conclude(PR, 'refused', { reason: 'tests failed' })
    a.record(PR2); a.conclude(PR2, 'merged', { machine: 'mac-mini-1' })
    expect(a.waiting()).toEqual([])
  })

  it('waiting is oldest click first', () => {
    let t = 0
    const a = createApprovalLedger(file, { now: () => ++t })
    a.record(PR2); a.conclude(PR2, 'queued')
    a.record(PR); a.conclude(PR, 'queued')
    expect(a.waiting().map((x) => x.url)).toEqual([PR2, PR])
  })

  it('a corrupt or missing file is an empty ledger, never a crash (and the next write repairs it)', () => {
    writeFileSync(file, '{nope')
    const a = createApprovalLedger(file)
    expect(a.waiting()).toEqual([])
    a.record(PR)
    expect(createApprovalLedger(file).get(PR).outcome).toBe('sending')
    expect(createApprovalLedger(path.join(dir, 'missing', 'x.json')).waiting()).toEqual([])
  })

  it('bounded: old concluded entries are dropped past the cap, waiting ones never are', () => {
    let t = 0
    const a = createApprovalLedger(file, { now: () => ++t, cap: 3 })
    a.record(PR); a.conclude(PR, 'queued')
    for (let i = 0; i < 6; i++) { const u = `https://github.com/G-Eskayo/marvin/pull/${i}`; a.record(u); a.conclude(u, 'merged') }
    const all = JSON.parse(readFileSync(file, 'utf8')).approvals
    expect(all.length).toBeLessThanOrEqual(4)
    expect(a.waiting().map((x) => x.url)).toEqual([PR])
  })

  it('drop removes a waiting approval (Deny cancels it)', () => {
    const a = createApprovalLedger(file)
    a.record(PR); a.conclude(PR, 'queued')
    a.drop(PR)
    expect(a.waiting()).toEqual([])
  })
})

describe('approval retry: a saved approval merges when a machine comes back, without another click', () => {
  let dir, ledger
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'retry-')); ledger = createApprovalLedger(path.join(dir, 'approvals.json')) })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))
  const queued = (...urls) => urls.forEach((u) => { ledger.record(u); ledger.conclude(u, 'queued') })

  it('the trigger retries each waiting approval once, through the same approve path, oldest first', async () => {
    queued(PR, PR2)
    const sent = []
    const retry = createApprovalRetry({ ledger, viewPr: async () => ({ state: 'OPEN' }), approve: async (url) => { sent.push(url); ledger.conclude(url, 'merged'); return { merged: true } } })
    const r = await retry.run('merge-host-up')
    expect(sent).toEqual([PR, PR2])
    expect(r).toMatchObject({ tried: 2 })
    expect(ledger.waiting()).toEqual([])
  })

  it('still no machine: stops at the first, leaves all queued (no burst of doomed requests)', async () => {
    queued(PR, PR2)
    const sent = []
    const retry = createApprovalRetry({ ledger, viewPr: async () => ({ state: 'OPEN' }), approve: async (url) => { sent.push(url); return { queued: true } } })
    await retry.run('resume')
    expect(sent).toEqual([PR])
    expect(ledger.waiting().map((x) => x.url)).toEqual([PR, PR2])
  })

  it('a PR merged or closed meanwhile (by hand on GitHub) is concluded, never sent again', async () => {
    queued(PR, PR2)
    const sent = []
    const states = { [PR]: 'MERGED', [PR2]: 'CLOSED' }
    const retry = createApprovalRetry({ ledger, viewPr: async (u) => ({ state: states[u] }), approve: async (url) => { sent.push(url) } })
    await retry.run('startup')
    expect(sent).toEqual([])
    expect(ledger.get(PR).outcome).toBe('merged-elsewhere')
    expect(ledger.get(PR2).outcome).toBe('closed')
  })

  it('GitHub unreachable for the state check: leave it queued for the next trigger, do not send blind', async () => {
    queued(PR)
    const sent = []
    const retry = createApprovalRetry({ ledger, viewPr: async () => { throw new Error('offline') }, approve: async (url) => { sent.push(url) } })
    await retry.run('online')
    expect(sent).toEqual([])
    expect(ledger.waiting()).toHaveLength(1)
  })

  it('two triggers at once (webhook up + resume): one pass runs, then one more for whatever is still waiting', async () => {
    queued(PR)
    let calls = 0, release
    const gate = new Promise((r) => (release = r))
    const retry = createApprovalRetry({ ledger, viewPr: async () => ({ state: 'OPEN' }), approve: async (url) => { calls++; await gate; ledger.conclude(url, 'merged') } })
    const a = retry.run('merge-host-up')
    const b = retry.run('resume')
    const c = retry.run('online')
    release()
    await Promise.all([a, b, c])
    expect(calls).toBe(1)
  })

  it('an approve that throws (a gate refusal) does not stop the rest', async () => {
    queued(PR, PR2)
    const sent = []
    const retry = createApprovalRetry({ ledger, viewPr: async () => ({ state: 'OPEN' }), approve: async (url) => { sent.push(url); if (url === PR) { ledger.conclude(url, 'refused'); throw new Error('tests failed') } ledger.conclude(url, 'merged') } })
    await retry.run('merge-host-up')
    expect(sent).toEqual([PR, PR2])
  })
})

describe('acceptance: the Mini returning mid-merge does not merge twice', () => {
  let dir, ledger
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'twice-')); ledger = createApprovalLedger(path.join(dir, 'approvals.json')) })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))

  it('a merge running on the MacBook holds the op; the Mini coming back (retry trigger) sends nothing for that PR', async () => {
    const miniCalls = [], bookCalls = []
    let finishLocal
    const book = await serve((req, res, raw) => {
      bookCalls.push(JSON.parse(raw).pr_url)
      const reply = approveResponder(res, { streaming: true })
      reply.event({ id: 'b', seq: 1, stage: 'tests', state: 'running', at: 1 })
      finishLocal = () => reply.result(200, { merged: true })
    })
    const mini = await serve(merging(miniCalls))
    const ops = createMergeOps()
    let machines = [MINI(await closedPortUrl()), BOOK(book)]
    // The real flow the IPC handler and the retry both use.
    const approve = createApproveFlow({ mergeOps: ops, ledger, machines: () => machines, send: (u, url, o) => approveMrStream(u, url, { ...o, connectTimeoutMs: 300 }) })
    const click = approve(PR, { number: 900 })
    while (!finishLocal) await new Promise((r) => setTimeout(r, 5))
    // The Mini is back: its startup announcement fires a retry pass. The click is mid-merge on the MacBook.
    machines = [MINI(mini), BOOK(book)]
    const retry = createApprovalRetry({ ledger, viewPr: async () => ({ state: 'OPEN' }), approve: (url) => approve(url, { retry: true }) })
    await retry.run('merge-host-up')
    // A second click on the card while it merges is refused by the same op.
    expect(await approve(PR)).toMatchObject({ alreadyMerging: true })
    finishLocal()
    expect((await click).merged).toBe(true)
    expect(bookCalls).toEqual([PR])
    expect(miniCalls).toEqual([])
  })
})

describe('createApproveFlow: one approval from click to outcome', () => {
  let dir, ledger, ops, pushed
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'flow-')); ledger = createApprovalLedger(path.join(dir, 'a.json')); ops = createMergeOps(); pushed = [] })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))
  const flow = (machines, extra = {}) => createApproveFlow({ mergeOps: ops, ledger, machines: () => machines, send: (u, url, o) => approveMrStream(u, url, { ...o, connectTimeoutMs: 300 }), push: (u, op) => op && pushed.push(op), ...extra })

  it('the click is in the ledger before the request leaves', async () => {
    let seenAtSend
    const url = await serve((req, res) => { seenAtSend = ledger.get(PR); approveResponder(res, { streaming: true }).result(200, { merged: true }) })
    await flow([MINI(url)])(PR, { number: 900, head: 'abc' })
    expect(seenAtSend).toMatchObject({ url: PR, number: 900, head: 'abc', outcome: 'sending' })
    expect(ledger.get(PR)).toMatchObject({ outcome: 'merged', machine: 'mac-mini-1' })
  })

  it('failover: the card gets the notice while it merges on the MacBook, and the ledger says which machine merged it', async () => {
    const calls = []
    const book = await serve(merging(calls))
    const r = await flow([MINI(await closedPortUrl()), BOOK(book)])(PR)
    expect(r.merged).toBe(true)
    expect(pushed.some((op) => op.state === 'merging' && op.notice === 'The Mac mini is offline, merging on this MacBook Pro instead.')).toBe(true)
    expect(ledger.get(PR)).toMatchObject({ outcome: 'merged', machine: 'macbook-pro-1' })
    expect(ops.get(PR).state).toBe('merged')
  })

  it('both down: queued on the card with the reason, saved in the ledger as waiting, and the result says queued', async () => {
    const r = await flow([MINI(await closedPortUrl()), BOOK(await closedPortUrl())])(PR)
    expect(r).toMatchObject({ merged: false, queued: true, cancelled: false })
    expect(r.reason).toMatch(/^Neither Mac can merge right now/)
    expect(ops.get(PR)).toMatchObject({ state: 'queued', reason: r.reason })
    expect(ledger.waiting().map((a) => a.url)).toEqual([PR])
  })

  it('a refusal is recorded as refused (not retried) and thrown to the card as before', async () => {
    const url = await serve((req, res) => approveResponder(res, { streaming: true }).result(503, { code: 'GATE_INFRA', stage: 'gate', action: 'escalate', message: 'disk' }))
    await expect(flow([MINI(url)])(PR)).rejects.toThrow(/GATE_INFRA/)
    expect(ledger.get(PR).outcome).toBe('refused')
    expect(ledger.waiting()).toEqual([])
  })

  it('the opt-in popup cancelled: nothing recorded, nothing sent', async () => {
    const calls = []
    const url = await serve(merging(calls))
    const r = await flow([MINI(url)], { confirm: async () => false })(PR)
    expect(r).toEqual({ merged: false, cancelled: true })
    expect(ledger.get(PR)).toBe(null)
    expect(calls).toEqual([])
  })

  it('a retry skips the popup (the click already happened)', async () => {
    const calls = []
    const url = await serve(merging(calls))
    let asked = 0
    await flow([MINI(url)], { confirm: async () => { asked++; return false } })(PR, { retry: true })
    expect([asked, calls]).toEqual([0, [PR]])
  })

  it('end to end: both down, queued; the MacBook webhook comes back, its trigger merges it without a click', async () => {
    let machines = [MINI(await closedPortUrl()), BOOK(await closedPortUrl())]
    const approve = createApproveFlow({ mergeOps: ops, ledger, machines: () => machines, send: (u, url, o) => approveMrStream(u, url, { ...o, connectTimeoutMs: 300 }) })
    expect((await approve(PR)).queued).toBe(true)
    const calls = []
    machines = [machines[0], BOOK(await serve(merging(calls)))]
    await createApprovalRetry({ ledger, viewPr: async () => ({ state: 'OPEN' }), approve: (url) => approve(url, { retry: true }) }).run('merge-host-up')
    expect(calls).toEqual([PR])
    expect(ledger.get(PR)).toMatchObject({ outcome: 'merged', machine: 'macbook-pro-1', attempts: 2 })
    expect(ops.get(PR).state).toBe('merged')
  })
})
