import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createServer } from 'http'
import { mkdtempSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { approveMrStream } from '../electron/main/approve_stream.js'
import { approveResponder } from '../webhook-server/merge_progress.js'
import { createMergeOps } from '../electron/main/merge_ops.js'
import { createApprovalLedger } from '../electron/main/approval_ledger.js'
import { createApprovalRetry } from '../electron/main/approval_retry.js'
import { createApproveFlow } from '../electron/main/approve_flow.js'
import { describePrState } from '../src/lib/prState.js'
import { statusFromOp } from '../src/components/MrReview.jsx'
import { memoryGuardCheck, forgetQueuedMerge } from '../webhook-server/merge.js'

// marvin#940 part 3, "keep the promise": the Mini refused PR #238 for memory and said it would start by itself, but
// the card read "failed" and the owner approved it again. A refusal for memory that the Mini queued is an approval
// that waits: saved in the ledger as waiting-memory, the card says "Approved: waiting for memory on the Mac mini",
// it runs by itself on the Mini (memory_guard.py's queue), and the next trigger concludes it, never twice.

const PR = 'https://github.com/G-Eskayo/clarity-captions/pull/238'
const servers = []
afterEach(async () => { await Promise.all(servers.splice(0).map((s) => new Promise((r) => s.close(() => r())))) })
function serve(handler) {
  const s = createServer((req, res) => { let raw = ''; req.on('data', (c) => (raw += c)); req.on('end', () => handler(req, res, raw)) })
  servers.push(s)
  return new Promise((r) => s.listen(0, '127.0.0.1', () => r(`http://127.0.0.1:${s.address().port}/approve`)))
}
const MINI = (url) => ({ id: 'mac-mini-1', label: 'Mac mini', url, here: false })
const MESSAGE = "The Mac mini's memory is under pressure, so PR #238 waits. Nothing was stopped to make room. Pressure: warn, 2.6 GB of swap in use. It starts by itself when pressure drops."
const memoryRefusal = (action = 'retry', calls = []) => (req, res, raw) => {
  calls.push(JSON.parse(raw).pr_url)
  approveResponder(res, { streaming: true }).result(500, { merged: false, code: 'MEMORY_PRESSURE', stage: 'gate', action, message: MESSAGE, error: `MEMORY_PRESSURE at gate: ${MESSAGE}` })
}

let dir, ledger, ops, pushed
beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'mem-wait-')); ledger = createApprovalLedger(path.join(dir, 'a.json')); ops = createMergeOps(); pushed = [] })
afterEach(() => rmSync(dir, { recursive: true, force: true }))
const flow = (machines) => createApproveFlow({ mergeOps: ops, ledger, machines: () => machines, send: (u, url, o) => approveMrStream(u, url, { ...o, connectTimeoutMs: 300 }), push: (u, op) => op && pushed.push(op) })

describe('a refusal for memory that the Mini queued is a waiting approval, not a failure', () => {
  it('the card waits, the ledger says waiting-memory on the Mini, and nothing is thrown', async () => {
    const r = await flow([MINI(await serve(memoryRefusal()))])(PR, { number: 238 })
    expect(r).toMatchObject({ merged: false, waitingMemory: true, machine: 'mac-mini-1', cancelled: false })
    expect(ledger.get(PR)).toMatchObject({ outcome: 'waiting-memory', machine: 'mac-mini-1' })
    expect(ledger.waiting().map((a) => a.url)).toEqual([PR])
    expect(ops.get(PR)).toMatchObject({ state: 'waiting-memory', machine: 'Mac mini', reason: MESSAGE })
    expect(pushed.at(-1).state).toBe('waiting-memory')
  })

  it('a memory refusal the Mini did NOT queue is still a refusal, as before (Approve again)', async () => {
    await expect(flow([MINI(await serve(memoryRefusal('escalate')))])(PR)).rejects.toThrow(/MEMORY_PRESSURE/)
    expect(ledger.get(PR).outcome).toBe('refused')
  })

  it('the card: "Approved: waiting for memory on the Mac mini", with the Mini\'s own words; no Approve, Deny cancels', () => {
    const v = statusFromOp({ state: 'waiting-memory', machine: 'Mac mini', reason: MESSAGE })
    expect(v).toMatchObject({ status: 'waiting-memory', errorMessage: MESSAGE, machine: 'Mac mini' })
    const view = describePrState({ checks: { state: 'passing', failing: [], pending: [] } }, { status: 'waiting-memory', errorMessage: MESSAGE, machine: 'Mac mini' })
    expect(view).toMatchObject({ kind: 'queued', tone: 'working', headline: 'Approved: waiting for memory on the Mac mini', detail: MESSAGE, approve: 'hidden', deny: 'enabled' })
  })

  it('a waiting-memory op is kept when the PR\'s head moves on (it is still the approval that waits)', () => {
    ops.start(PR, 1, 'abc')
    ops.waitMemory(PR, MESSAGE, 'Mac mini')
    expect(ops.get(PR, Date.now(), 'def').state).toBe('waiting-memory')
  })
})

describe('the trigger concludes it, never merges it twice', () => {
  const waitingOnMini = () => { ledger.record(PR, { number: 238 }); ledger.conclude(PR, 'waiting-memory', { machine: 'mac-mini-1', reason: MESSAGE }) }

  it('merged by the Mini\'s own queue meanwhile: concluded as merged by the Mini, nothing sent', async () => {
    waitingOnMini()
    const approve = vi.fn()
    await createApprovalRetry({ ledger, viewPr: async () => ({ state: 'MERGED' }), approve }).run('merge-host-up:mac-mini-1')
    expect(approve).not.toHaveBeenCalled()
    expect(ledger.get(PR)).toMatchObject({ outcome: 'merged', machine: 'mac-mini-1' })
    expect(ledger.waiting()).toEqual([])
  })

  it('still open: sent again through the same path; still under pressure, it stays waiting (the Mini keeps one queued copy)', async () => {
    waitingOnMini()
    const calls = []
    const approve = flow([MINI(await serve(memoryRefusal('retry', calls)))])
    await createApprovalRetry({ ledger, viewPr: async () => ({ state: 'OPEN' }), approve: (u, o) => approve(u, o) }).run('merge-host-up:mac-mini-1')
    expect(calls).toEqual([PR])
    expect(ledger.get(PR)).toMatchObject({ outcome: 'waiting-memory', machine: 'mac-mini-1' })
  })

  it('the Mini\'s queued run is merging it right now (ALREADY_MERGING): it stays waiting, the try not counted, no error', async () => {
    waitingOnMini()
    const url = await serve((req, res) => approveResponder(res, { streaming: true }).result(409, { merged: false, code: 'ALREADY_MERGING', stage: 'queued', message: 'The Mac mini is already merging this PR.' }))
    const r = await flow([MINI(url)])(PR, { retry: true })
    expect(r).toMatchObject({ merged: false, waitingMemory: true })
    expect(ledger.get(PR)).toMatchObject({ outcome: 'waiting-memory', machine: 'mac-mini-1', attempts: 1 })
    expect(ops.get(PR).state).toBe('waiting-memory')
  })
})

describe('the Mini side: the queued run, and a merge that starts another way', () => {
  it('the queued Approve says it came from the memory queue (so its end tells the dashboards)', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '{"ok": true}' })
    await memoryGuardCheck(PR, 7878, exec)
    const cmd = exec.mock.calls[0][1]
    const curl = cmd.slice(cmd.indexOf('--') + 1)
    expect(JSON.parse(curl[curl.indexOf('--data') + 1])).toEqual({ pr_url: PR, by: 'memory-queue' })
  })

  it('a merge that starts drops the same PR\'s queued copy, so the queue never runs it a second time', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '{"forgotten": true}\n' })
    expect(await forgetQueuedMerge(PR, exec)).toBe(true)
    expect(exec.mock.calls[0][1].slice(1)).toEqual(['forget', '--key', `merge:${PR}`])
    expect(await forgetQueuedMerge(PR, vi.fn().mockRejectedValue(new Error('no python')))).toBe(false)
  })
})
