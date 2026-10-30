import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createServer } from 'http'
import { mkdtempSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { approveMrStream } from '../electron/main/approve_stream.js'
import { approveResponder } from '../webhook-server/merge_progress.js'
import { createMergeOps } from '../electron/main/merge_ops.js'
import { createApprovalLedger } from '../electron/main/approval_ledger.js'
import { createApproveFlow } from '../electron/main/approve_flow.js'
import { mergeMachines, askReady, askForget } from '../electron/main/merge_failover.js'
import { describePrState } from '../src/lib/prState.js'
import { statusFromOp } from '../src/components/MrReview.jsx'
import { readMergeReady } from '../webhook-server/merge.js'

// marvin#940 part 4: when the Mac mini can't merge for memory, the next merge machine takes it, but only when it says
// it is fit (GET /merge-ready: awake, on power, at home, idle) and only after the Mini has dropped its own queued copy
// (POST /merge-forget). Either step failing leaves the approval waiting on the Mini: it never merges twice. Each Mac is
// a real HTTP server here, the shape of its webhook.

const PR = 'https://github.com/G-Eskayo/clarity-captions/pull/238'
const MEM = "The Mac mini's memory is under pressure, so PR #238 waits. Nothing was stopped to make room. Pressure: warn. It starts by itself when pressure drops."
const servers = []
afterEach(async () => { await Promise.all(servers.splice(0).map((s) => new Promise((r) => s.close(() => r())))) })

// A webhook: /approve answers with `approve`, /merge-ready with `ready`, /merge-forget with `forgotten`. Logs calls.
function mac({ approve = 'merge', ready = { ready: true, why: [], os: 'macOS 27.0' }, forgotten = true } = {}) {
  const calls = []
  const s = createServer((req, res) => {
    let raw = ''
    req.on('data', (c) => (raw += c))
    req.on('end', () => {
      const route = req.url.split('?')[0]
      calls.push(route + (req.url.includes('?') ? `?${req.url.split('?')[1]}` : ''))
      if (route === '/merge-ready') return res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(ready))
      if (route === '/merge-forget') return res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ forgotten }))
      const reply = approveResponder(res, { streaming: true })
      if (approve === 'memory') return reply.result(500, { merged: false, code: 'MEMORY_PRESSURE', stage: 'gate', action: 'retry', message: MEM })
      reply.event({ id: 'x', seq: 1, stage: 'queued', state: 'running', at: 1 })
      reply.result(200, { merged: true, reengaged: false, reason: null })
    })
  })
  servers.push(s)
  return new Promise((r) => s.listen(0, '127.0.0.1', () => r({ url: `http://127.0.0.1:${s.address().port}/approve`, calls })))
}
async function deadUrl() {
  const s = createServer()
  await new Promise((r) => s.listen(0, '127.0.0.1', r))
  const port = s.address().port
  await new Promise((r) => s.close(r))
  return `http://127.0.0.1:${port}/approve`
}
const MINI = (url) => ({ id: 'mac-mini-1', label: 'Mac mini', url, here: false })
const LINUX = (url) => ({ id: 'linux-box-1', label: 'Linux box', url, here: false })
const BOOK = (url) => ({ id: 'macbook-pro-1', label: 'MacBook Pro', url, here: true })
const approves = (calls) => calls.filter((c) => c === '/approve').length

let dir, ledger, ops, pushed
beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'backup-')); ledger = createApprovalLedger(path.join(dir, 'a.json')); ops = createMergeOps(); pushed = [] })
afterEach(() => rmSync(dir, { recursive: true, force: true }))
const flow = (machines) => createApproveFlow({
  mergeOps: ops, ledger, machines: () => machines,
  send: (u, url, o) => approveMrStream(u, url, { ...o, connectTimeoutMs: 300 }),
  ready: (m, repo) => askReady(m, repo, { timeoutMs: 1000 }),
  forget: (m, prUrl) => askForget(m, prUrl, { timeoutMs: 1000 }),
  push: (u, op) => op && pushed.push(op)
})

describe('the Mini is short of memory and the MacBook is fit: it merges on the MacBook, and says so', () => {
  it('asks the MacBook, has the Mini drop its queued copy, merges on the MacBook, and names it', async () => {
    const mini = await mac({ approve: 'memory', ready: { ready: false, why: ['its memory is under pressure'], os: 'macOS 26.5.1' } })
    const book = await mac()
    const r = await flow([MINI(mini.url), BOOK(book.url)])(PR, { number: 238 })
    expect(r).toMatchObject({ merged: true, cancelled: false })
    expect(book.calls).toContain('/merge-ready?repo=G-Eskayo%2Fclarity-captions')
    expect(mini.calls).toContain('/merge-forget')
    expect(approves(mini.calls)).toBe(1)
    expect(approves(book.calls)).toBe(1)
    expect(pushed.some((op) => op.state === 'merging' && op.notice === "The Mac mini's memory is under pressure, merging on this MacBook Pro instead.")).toBe(true)
    expect(ledger.get(PR)).toMatchObject({ outcome: 'merged', machine: 'macbook-pro-1' })
    expect(ops.get(PR)).toMatchObject({ state: 'merged', mergedOn: 'this MacBook Pro' })
  })

  it('a different macOS on the MacBook is flagged: its tests may answer differently from the Mini\'s (#826 item 5)', async () => {
    const mini = await mac({ approve: 'memory', ready: { ready: false, why: [], os: 'macOS 26.5.1' } })
    const book = await mac({ ready: { ready: true, why: [], os: 'macOS 27.0' } })
    await flow([MINI(mini.url), BOOK(book.url)])(PR)
    const note = 'Its tests ran on macOS 27.0; the Mac mini runs macOS 26.5.1, so a test that depends on the machine may answer differently there.'
    expect(ops.get(PR).note).toBe(note)
    expect(ledger.get(PR).reason).toBe(note)
  })

  it('the same macOS: no flag', async () => {
    const mini = await mac({ approve: 'memory', ready: { ready: false, why: [], os: 'macOS 27.0' } })
    const book = await mac({ ready: { ready: true, why: [], os: 'macOS 27.0' } })
    await flow([MINI(mini.url), BOOK(book.url)])(PR)
    expect(ops.get(PR).note ?? null).toBe(null)
  })

  it('the card: "Merged", and on which Mac', () => {
    const op = { state: 'merged', mergedOn: 'this MacBook Pro', note: 'Its tests ran on macOS 27.0; the Mac mini runs macOS 26.5.1, so a test that depends on the machine may answer differently there.' }
    const v = statusFromOp(op)
    const view = describePrState({}, { status: v.status, errorMessage: v.errorMessage, machine: v.machine })
    expect(view).toMatchObject({ kind: 'merged', headline: 'Merged', detail: `Merged on this MacBook Pro. ${op.note}` })
  })
})

describe('never merged twice, never on a Mac that is not fit', () => {
  it('the MacBook is not fit (on battery): it waits on the Mini; the MacBook is never sent it, the Mini keeps its copy', async () => {
    const mini = await mac({ approve: 'memory' })
    const book = await mac({ ready: { ready: false, why: ['it is on battery'], os: 'macOS 27.0' } })
    const r = await flow([MINI(mini.url), BOOK(book.url)])(PR)
    expect(r).toMatchObject({ waitingMemory: true, machine: 'mac-mini-1' })
    expect(approves(book.calls)).toBe(0)
    expect(mini.calls).not.toContain('/merge-forget')
    expect(ledger.get(PR).outcome).toBe('waiting-memory')
  })

  it('the Mini already started its queued copy (forget answers false): the MacBook is never sent it', async () => {
    const mini = await mac({ approve: 'memory', forgotten: false })
    const book = await mac()
    const r = await flow([MINI(mini.url), BOOK(book.url)])(PR)
    expect(r.waitingMemory).toBe(true)
    expect(approves(book.calls)).toBe(0)
  })

  it('the MacBook does not answer whether it is fit: waits on the Mini', async () => {
    const mini = await mac({ approve: 'memory' })
    const r = await flow([MINI(mini.url), BOOK(await deadUrl())])(PR)
    expect(r.waitingMemory).toBe(true)
    expect(mini.calls).not.toContain('/merge-forget')
  })

  it('the MacBook vanishes after the Mini dropped its copy: sent back to the Mini, which queues it again', async () => {
    const mini = await mac({ approve: 'memory' })
    let bookUrl
    const ready = createServer((req, res) => res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ ready: true, why: [], os: 'macOS 27.0' })))
    servers.push(ready)
    await new Promise((r) => ready.listen(0, '127.0.0.1', r))
    // ready answers on one port, but its /approve is on a closed port: a Mac that went to sleep in between
    const book = { ...BOOK(await deadUrl()), readyUrl: `http://127.0.0.1:${ready.address().port}/merge-ready` }
    bookUrl = book.url
    const r = await flow([MINI(mini.url), book])(PR)
    expect(bookUrl).toBeTruthy()
    expect(r).toMatchObject({ waitingMemory: true, machine: 'mac-mini-1' })
    expect(approves(mini.calls)).toBe(2)
    expect(ledger.get(PR).outcome).toBe('waiting-memory')
  })

  it('a third machine slots in (marvin#945): the Linux box is asked first and skipped for a Seal PR; the MacBook merges it', async () => {
    const mini = await mac({ approve: 'memory' })
    const linux = await mac({ ready: { ready: false, why: ['this project needs a Mac with Xcode'], os: 'Linux 6.8' } })
    const book = await mac()
    const r = await flow([MINI(mini.url), LINUX(linux.url), BOOK(book.url)])(PR)
    expect(r.merged).toBe(true)
    expect(approves(linux.calls)).toBe(0)
    expect(ledger.get(PR).machine).toBe('macbook-pro-1')
  })

  it('an unreachable Mini still fails over as before (#766), with no fitness check', async () => {
    const book = await mac()
    const r = await flow([MINI(await deadUrl()), BOOK(book.url)])(PR)
    expect(r.merged).toBe(true)
    expect(book.calls.some((c) => c.startsWith('/merge-ready'))).toBe(false)
  })
})

describe('the machine list', () => {
  it('backups go between the Mini and this Mac, in order', () => {
    const list = mergeMachines({ primaryUrl: 'http://mini:7878/approve', primaryId: 'mac-mini-1', localId: 'macbook-pro-1', backups: [{ id: 'linux-box-1', url: 'http://linux:7878/approve' }] })
    expect(list.map((m) => m.id)).toEqual(['mac-mini-1', 'linux-box-1', 'macbook-pro-1'])
    expect(list[1]).toMatchObject({ label: expect.any(String), here: false })
  })
})

describe('the webhook side of /merge-ready', () => {
  it('asks lib/merge_backup.py for this repo and passes its answer on', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '{"ready": true, "why": [], "machine": "macbook-pro-1", "os": "macOS 27.0"}\n' })
    expect(await readMergeReady('G-Eskayo/marvin', exec)).toEqual({ ready: true, why: [], machine: 'macbook-pro-1', os: 'macOS 27.0' })
    expect(exec.mock.calls[0][1].slice(1)).toEqual(['ready', '--repo', 'G-Eskayo/marvin'])
  })

  it('a check that fails is "not fit", never a crash', async () => {
    const r = await readMergeReady('G-Eskayo/marvin', vi.fn().mockRejectedValue(new Error('boom')))
    expect(r.ready).toBe(false)
    expect(r.why[0]).toMatch(/couldn't check/)
  })
})
