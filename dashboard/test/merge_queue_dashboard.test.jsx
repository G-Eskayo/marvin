import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createServer } from 'http'
import { mkdtempSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { renderToStaticMarkup } from 'react-dom/server'
import { approveResponder } from '../webhook-server/merge_progress.js'
import { approveMrStream } from '../electron/main/approve_stream.js'
import { createMergeOps } from '../electron/main/merge_ops.js'
import { createApprovalLedger } from '../electron/main/approval_ledger.js'
import { createApproveFlow } from '../electron/main/approve_flow.js'
import { listPipelinePrs, queueLines } from '../electron/main/mr_review.js'
import { QueueLine } from '../src/components/MrReview.jsx'

// marvin#231, the dashboard's side: an Approve the merge Mac queues is neither a merge nor a refusal, and every card's
// line comes from the same mergeOrder() the merge Mac runs, fed with the queue it serves at GET /merge-queue.
const REPO = 'G-Eskayo/marvin'
const url = (n) => `https://github.com/${REPO}/pull/${n}`
const green = [{ __typename: 'CheckRun', name: 'tests', status: 'COMPLETED', conclusion: 'SUCCESS' }]
const raw = (n, extra = {}) => ({ number: n, url: url(n), repo: REPO, title: `PR ${n}`, body: `Closes #${n - 9}`, baseRefName: 'main',
  headRefName: `ticket/${n - 9}`, headRefOid: `sha${n}`, mergeable: 'MERGEABLE', statusCheckRollup: green, files: [], ...extra })

const servers = []
afterEach(async () => { await Promise.all(servers.splice(0).map((s) => new Promise((r) => s.close(() => r())))) })
function serve(handler) {
  const s = createServer((req, res) => { let b = ''; req.on('data', (c) => (b += c)); req.on('end', () => handler(req, res, b)) })
  servers.push(s)
  return new Promise((r) => s.listen(0, '127.0.0.1', () => r(`http://127.0.0.1:${s.address().port}/approve`)))
}

let dir, ledger, ops, pushed, afters
beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'mq-dash-')); ledger = createApprovalLedger(path.join(dir, 'a.json')); ops = createMergeOps(); pushed = []; afters = [] })
afterEach(() => rmSync(dir, { recursive: true, force: true }))

describe('an Approve the merge Mac queued', () => {
  it('is not a merge and not a refusal: the op ends, the ledger says merge-queue, the list is asked to refresh', async () => {
    const at = await serve((req, res) => approveResponder(res, { streaming: true }).result(200, { merged: false, mergeQueued: true, url: url(942), state: 'waiting', reason: "waits for #941 (it's built on it)" }))
    const flow = createApproveFlow({ mergeOps: ops, ledger, machines: () => [{ id: 'mac-mini-1', label: 'Mac mini', url: at, here: false }],
      send: (u, target, o) => approveMrStream(u, target, { ...o, connectTimeoutMs: 300 }), push: (u, op) => op && pushed.push(op), after: (u, r) => afters.push(r) })
    const r = await flow(url(942), { number: 942 })
    expect(r).toMatchObject({ merged: false, mergeQueued: true, cancelled: false, reason: "waits for #941 (it's built on it)" })
    expect(ledger.get(url(942))).toMatchObject({ outcome: 'merge-queue', machine: 'mac-mini-1' })
    expect(ledger.waiting()).toEqual([])        // not retried by this Mac: the merge Mac holds it now
    expect(ops.get(url(942)).state).toBe('idle')
    expect(pushed.at(-1)).toEqual({ state: 'idle' })
    expect(afters).toHaveLength(1)
  })
})

describe('each card\'s queue line', () => {
  const chain = () => [raw(941), raw(942, { baseRefName: 'ticket/932' })]
  const facts = (over = {}) => ({ repos: {}, facts: { unbuilt: [], repairFailed: {}, health: { ok: true }, ...over } })

  it('#941 and #942 (answers in, only main merged in since): "your answers aren\'t built yet", not queued', async () => {
    const list = await listPipelinePrs(async () => chain(), { mergeQueue: async () => facts({ unbuilt: [url(941), url(942)] }), issuesFor: () => [] })
    expect(list.map((p) => p.mergeQueue.reason)).toEqual(["your answers aren't built yet", "your answers aren't built yet"])
    expect(list.every((p) => p.mergeQueue.queued === false && p.mergeQueue.tone === 'amber')).toBe(true)
  })

  it('once built, #942 waits for #941; approved, #941 shows its place in sky', async () => {
    const queue = { repos: { [REPO]: { items: [{ url: url(942), approvedAt: 1 }, { url: url(941), approvedAt: 2 }], failed: {}, running: null } }, facts: facts().facts }
    const list = await listPipelinePrs(async () => chain(), { mergeQueue: async () => queue, issuesFor: () => [] })
    expect(list[0].mergeQueue).toMatchObject({ queued: true, state: 'queued', tone: 'sky', reason: 'queued · 1st · starts next' })
    expect(list[1].mergeQueue).toMatchObject({ queued: true, state: 'waiting', reason: "waits for #941 (it's built on it)" })
  })

  it('main-red from the boards\' tickets holds every PR but the fix', async () => {
    const issues = [{ number: 978, title: 'Main is red at 9f4: fix forward', state: 'OPEN', labels: [{ name: 'main-red' }] }]
    const prs = [raw(970), raw(986, { body: 'Closes #978' })]
    const list = await listPipelinePrs(async () => prs, { mergeQueue: async () => facts(), issuesFor: (repo) => (repo === REPO ? issues : []) })
    expect(list[0].mergeQueue.reason).toBe('main is red · waits for #986')
    expect(list[1].mergeQueue.reason).toBeNull()
  })

  it('the merge server unreachable: no line claims a queue; a broken issue lookup never breaks the list', async () => {
    const list = await listPipelinePrs(async () => chain(), { mergeQueue: async () => { throw new Error('offline') }, issuesFor: () => { throw new Error('x') } })
    expect(list).toHaveLength(2)
    expect(list.every((p) => !p.mergeQueue?.queued)).toBe(true)
    expect(list[1].mergeQueue.reason).toBe("waits for #941 (it's built on it)")
    const none = await listPipelinePrs(async () => chain())
    expect(none.every((p) => p.mergeQueue === null)).toBe(true)
  })

  it('repos are worked out apart: a PR of another repo never waits on this repo\'s branches or main', () => {
    const other = { ...raw(5), url: 'https://github.com/G-Eskayo/clarity-captions/pull/5', repo: 'G-Eskayo/clarity-captions', baseRefName: 'ticket/932' }
    const lines = queueLines([raw(941), other], { queue: facts(), issuesFor: () => [{ number: 978, title: 'Main is red', labels: ['main-red'] }] })
    expect(lines[other.url].reason).toBe('targets ticket/932, which has no open PR · change its base to main')
    expect(lines[url(941)].reason).toBe('main is red · waits for #978')
  })

  it('renders as one small line, amber for waits and sky for queued, nothing when there is nothing to say', () => {
    expect(renderToStaticMarkup(<QueueLine entry={{ state: 'waiting', tone: 'amber', reason: "your answers aren't built yet" }} />)).toContain('text-amber-400')
    expect(renderToStaticMarkup(<QueueLine entry={{ state: 'queued', tone: 'sky', reason: 'queued · 2nd · starts after #971' }} />)).toContain('text-sky-400')
    expect(renderToStaticMarkup(<QueueLine entry={{ state: 'ready', reason: null }} />)).toBe('')
    expect(renderToStaticMarkup(<QueueLine entry={null} />)).toBe('')
  })
})
