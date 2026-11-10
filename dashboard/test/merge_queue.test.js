import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, readFileSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createMergeQueue, createQueueStore, outcomeFor, resumeInterrupted } from '../webhook-server/merge_queue.js'
import { enrichForOrder, mainStateFrom } from '../webhook-server/merge_order.js'
import { unbuiltFrom, createUnbuiltCache } from '../webhook-server/merge_facts.js'

// marvin#231: the queue runner against a small fake GitHub that behaves like the real one: a merge closes the PR, and
// the post-merge step moves PRs stacked on it onto main (post_merge_rebase.js does that for real). Real store on disk.
const REPO = 'G-Eskayo/marvin'
const url = (n) => `https://github.com/${REPO}/pull/${n}`
const green = [{ __typename: 'CheckRun', name: 'tests', status: 'COMPLETED', conclusion: 'SUCCESS' }]

function world(prs, { issues = [] } = {}) {
  const w = {
    prs: new Map(prs.map((p) => [p.number, { url: url(p.number), repo: REPO, title: `PR ${p.number}`, body: `Closes #${p.number + 1000}`, baseRefName: 'main',
      headRefName: `b${p.number}`, headRefOid: `sha${p.number}`, mergeable: 'MERGEABLE', statusCheckRollup: green, ...p }])),
    issues,
    unbuilt: new Set(),
    merged: [],
    runs: [],
    loads: 0,
    outcome: () => ({ result: { merged: true } })
  }
  w.load = async () => {
    w.loads++
    const open = [...w.prs.values()].map((p) => ({ ...p }))
    return { openPrs: enrichForOrder(open, { repo: REPO, issues: w.issues, unbuilt: w.unbuilt }), mainState: mainStateFrom({ issues: w.issues }) }
  }
  w.run = async (u) => {
    const n = Number(u.split('/').pop())
    w.runs.push({ n, head: w.prs.get(n)?.headRefOid })
    const out = await w.outcome(n)
    if (out.result?.merged) {
      const head = w.prs.get(n).headRefName
      w.prs.delete(n)
      w.merged.push(n)
      w.pendingRetarget = head
    }
    return out
  }
  // What post_merge_rebase.js does after a merge, in the repo's job line: stacked PRs move onto main.
  w.afterRun = async () => {
    for (const p of w.prs.values()) if (p.baseRefName === w.pendingRetarget) p.baseRefName = 'main'
    w.pendingRetarget = null
  }
  return w
}

let dir
let file
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'merge-queue-'))
  file = path.join(dir, 'merge-queue.json')
})
afterEach(() => rmSync(dir, { recursive: true, force: true }))

const make = (w, extra = {}) => {
  let t = 0
  const store = createQueueStore(file, { now: () => ++t })
  return { store, queue: createMergeQueue({ store, load: w.load, run: w.run, afterRun: w.afterRun, ...extra }) }
}

describe('merge queue runner', () => {
  it('the stacked chain #936 -> #941 -> #942, approved in reverse order, merges base first, each by itself', async () => {
    const w = world([{ number: 936 }, { number: 941, baseRefName: 'b936' }, { number: 942, baseRefName: 'b941' }])
    const { queue } = make(w)
    await queue.approve(REPO, url(942))
    await queue.approve(REPO, url(941))
    expect(w.merged).toEqual([])
    await queue.approve(REPO, url(936))
    expect(w.merged).toEqual([936, 941, 942])
    expect(createQueueStore(file).forRepo(REPO).items).toEqual([])
  })

  it('three PRs approved in one go merge in approval order with no further clicks', async () => {
    const w = world([{ number: 1 }, { number: 2 }, { number: 3 }])
    const { queue } = make(w)
    await Promise.all([queue.approve(REPO, url(2)), queue.approve(REPO, url(3)), queue.approve(REPO, url(1))])
    expect(w.merged).toEqual([2, 3, 1])
  })

  it('main red: only the fix merges; the rest wait and go once main is green (a trigger, not a timer)', async () => {
    const issues = [{ number: 978, title: 'Main is red at 9f4: fix forward', state: 'OPEN', labels: ['main-red'] }]
    const w = world([{ number: 970 }, { number: 986, body: 'Closes #978' }], { issues })
    const { queue } = make(w)
    w.outcome = (n) => { if (n === 986) w.issues = [] ; return { result: { merged: true } } }   // CI closes #978 on green
    await queue.approve(REPO, url(970))
    expect(w.merged).toEqual([])
    expect(queue.view(REPO).entries[url(970)].reason).toBe('main is red · waits for #986')
    await queue.approve(REPO, url(986))
    expect(w.merged).toEqual([986, 970])
  })

  it('main red with no fix open: nothing merges, and the green trigger releases it', async () => {
    const w = world([{ number: 970 }], { issues: [{ number: 978, title: 'Main is red', labels: ['main-red'] }] })
    const { queue } = make(w)
    await queue.approve(REPO, url(970))
    expect(w.runs).toEqual([])
    w.issues = []
    await queue.kick(REPO)
    expect(w.merged).toEqual([970])
  })

  it('answered-but-unbuilt Decisions never merge; the follow-up is asked for; once built it goes', async () => {
    const w = world([{ number: 941 }])
    w.unbuilt.add(url(941))
    const asked = []
    const { queue } = make(w, { onWaiting: (repo, p, e) => { if (e.unbuilt) asked.push(p.number) } })
    await queue.approve(REPO, url(941))
    await queue.kick(REPO)
    expect(w.runs).toEqual([])
    expect(asked).toContain(941)
    expect(queue.view(REPO).entries[url(941)].reason).toBe("your answers aren't built yet")
    w.unbuilt.clear()
    await queue.kick(REPO)
    expect(w.merged).toEqual([941])
  })

  it('a failure leaves the queue with its reason, the next one still merges, and dependents name the failure', async () => {
    const w = world([{ number: 936 }, { number: 941, baseRefName: 'b936' }, { number: 950 }])
    w.outcome = (n) => (n === 936 ? { result: { merged: false, reengaged: true, code: 'GATE_TESTS_FAILED', reason: '**Merge gate: tests failed**\n\ntest_box_trial failed' } } : { result: { merged: true } })
    const { queue, store } = make(w)
    await queue.approve(REPO, url(941))
    await queue.approve(REPO, url(936))
    await queue.approve(REPO, url(950))
    expect(w.merged).toEqual([950])
    const r = store.forRepo(REPO)
    expect(r.items.map((i) => i.number)).toEqual([941])
    expect(r.failed[url(936)].reason).toBe('GATE_TESTS_FAILED: test_box_trial failed')
    expect(queue.view(REPO).entries[url(941)].reason).toBe('waits for #936 (it failed: GATE_TESTS_FAILED: test_box_trial failed)')
  })

  it('a refusal (a thrown failure body) leaves with its message; approving again clears it', async () => {
    const w = world([{ number: 5 }])
    w.outcome = () => ({ body: { code: 'DECISIONS_PENDING', message: '1 Decision is waiting for you' } })
    const { queue, store } = make(w)
    await queue.approve(REPO, url(5))
    expect(store.forRepo(REPO).failed[url(5)]).toMatchObject({ code: 'DECISIONS_PENDING', reason: '1 Decision is waiting for you' })
    w.outcome = () => ({ result: { merged: true } })
    await queue.approve(REPO, url(5))
    expect(w.merged).toEqual([5])
    expect(store.forRepo(REPO).failed[url(5)]).toBeUndefined()
  })

  it('a disk-full gate (GATE_INFRA) is held, not dropped (#1097); approving again still forces a try', async () => {
    const w = world([{ number: 7 }])
    w.outcome = () => ({ body: { code: 'GATE_INFRA', message: "The Mac mini's disk is nearly full" } })
    const { queue, store } = make(w)
    await queue.approve(REPO, url(7))
    expect(store.forRepo(REPO).failed[url(7)]).toBeUndefined()
    expect(store.forRepo(REPO).items[0].hold).toMatchObject({ code: 'GATE_INFRA', until: 'later', reason: "The Mac mini's disk is nearly full" })
    w.outcome = () => ({ result: { merged: true } })
    await queue.approve(REPO, url(7))
    expect(w.merged).toEqual([7])
  })

  it('a run that throws is a failure, not a crash of the runner', async () => {
    const w = world([{ number: 1 }, { number: 2 }])
    w.outcome = (n) => { if (n === 1) throw new Error('boom'); return { result: { merged: true } } }
    const { queue, store } = make(w)
    await queue.approve(REPO, url(1))
    await queue.approve(REPO, url(2))
    expect(store.forRepo(REPO).failed[url(1)].reason).toBe('boom')
    expect(w.merged).toEqual([2])
  })

  it('a conflict goes to the resolver: it stays queued, is held on that commit, and goes after the resolver pushes', async () => {
    const w = world([{ number: 972 }, { number: 973 }])
    w.outcome = (n) => (n === 972 && w.prs.get(972).headRefOid === 'sha972' ? { result: { merged: false, reengaged: true, code: 'REBASE_CONFLICT', reason: 'conflict in a.js' } } : { result: { merged: true } })
    const resolver = []
    const { queue, store } = make(w, { onWaiting: (repo, p, e) => { if (e.conflict) resolver.push(p.headRefOid) } })
    await queue.approve(REPO, url(972))
    await queue.approve(REPO, url(973))
    expect(w.merged).toEqual([973])
    expect(store.forRepo(REPO).items.map((i) => i.number)).toEqual([972])
    expect(queue.view(REPO).entries[url(972)].reason).toBe('conflicts with main after #973 · MARVIN is fixing it')
    expect(resolver).toContain('sha972')
    w.prs.get(972).headRefOid = 'resolved'                  // the resolver's push
    await queue.kick(REPO)
    expect(w.merged).toEqual([973, 972])
    expect(w.runs.filter((r) => r.n === 972)).toHaveLength(2)
  })

  it('two Macs approving the same PR add it once and merge it once', async () => {
    const w = world([{ number: 7 }])
    let release
    w.outcome = () => new Promise((r) => { release = () => r({ result: { merged: true } }) })
    const { queue, store } = make(w)
    const first = queue.approve(REPO, url(7), { by: 'you' })
    await new Promise((r) => setTimeout(r, 0))
    const second = queue.approve(REPO, url(7), { by: 'you' })      // the other Mac, while the first is merging
    expect(store.forRepo(REPO).items).toHaveLength(1)
    expect(queue.isRunning(url(7))).toBe(true)
    release()
    await Promise.all([first, second])
    expect(w.runs).toHaveLength(1)
    expect(w.merged).toEqual([7])
  })

  it('an Approve that is not next is answered at once with its place; the one that is next is run with it attached', async () => {
    const w = world([{ number: 1 }, { number: 2 }])
    let release
    w.outcome = (n) => (n === 1 ? new Promise((r) => { release = () => r({ result: { merged: true } }) }) : { result: { merged: true } })
    const attached = []
    const run = w.run
    const { queue } = make(w, { run: async (u, a) => { attached.push([u, !!a]); return run(u) } })
    const answers = []
    const a1 = queue.approve(REPO, url(1), { attach: { url: url(1), queued: (e) => answers.push([1, e?.reason]) } })
    await new Promise((r) => setTimeout(r, 0))
    const a2 = queue.approve(REPO, url(2), { attach: { url: url(2), queued: (e) => answers.push([2, e?.reason]) } })
    await a2
    expect(answers).toEqual([[2, 'queued · 2nd · starts after #1']])
    release()
    await a1
    expect(attached).toEqual([[url(1), true], [url(2), false]])
    expect(w.merged).toEqual([1, 2])
  })

  it('new commits while queued keep its place, and the new commit is what is tested', async () => {
    const w = world([{ number: 1, statusCheckRollup: [{ __typename: 'CheckRun', name: 't', status: 'COMPLETED', conclusion: 'FAILURE' }] }, { number: 2 }])
    const { queue, store } = make(w)
    await queue.approve(REPO, url(1))                            // held: its checks fail
    const placed = store.forRepo(REPO).items[0].approvedAt
    Object.assign(w.prs.get(1), { headRefOid: 'fixed', statusCheckRollup: green })   // a new push, green
    await queue.approve(REPO, url(1))                            // approved again from the phone: same place
    expect(store.forRepo(REPO).items).toHaveLength(0)
    expect(w.runs).toEqual([{ n: 1, head: 'fixed' }])
    expect(placed).toBe(1)
  })

  it('a restart mid-queue picks up where it was: the queue is on disk and the interrupted merge runs again', async () => {
    const w = world([{ number: 1 }, { number: 2 }])
    w.outcome = () => new Promise(() => {})                     // the process dies mid-merge: this never answers
    const { queue } = make(w)
    queue.approve(REPO, url(1))
    queue.approve(REPO, url(2))
    await new Promise((r) => setTimeout(r, 5))
    expect(w.runs).toEqual([{ n: 1, head: 'sha1' }])
    // A new process: a new store and runner on the same file.
    w.outcome = () => ({ result: { merged: true } })
    const again = createMergeQueue({ store: createQueueStore(file), load: w.load, run: w.run, afterRun: w.afterRun })
    await again.kickAll()
    expect(w.merged).toEqual([1, 2])
  })

  it('a restart after the PR merged elsewhere drops it instead of merging it twice', async () => {
    const w = world([{ number: 1 }])
    createQueueStore(file).add(REPO, url(1))
    w.prs.delete(1)                                             // merged on GitHub by hand meanwhile
    const q = createMergeQueue({ store: createQueueStore(file), load: w.load, run: w.run })
    await q.kickAll()
    expect(w.runs).toEqual([])
    expect(createQueueStore(file).forRepo(REPO).items).toEqual([])
  })

  it('an empty queue does nothing on a trigger: no GitHub reads', async () => {
    const w = world([{ number: 1 }])
    const { queue } = make(w)
    expect(await queue.kick(REPO)).toBe(false)
    await queue.kickAll()
    expect(w.loads).toBe(0)
    expect(w.runs).toEqual([])
  })

  it('GitHub unreadable: nothing merges, the Approve is still answered, and it stays queued', async () => {
    const w = world([{ number: 1 }])
    const answers = []
    const { queue, store } = make(w, { load: async () => { throw new Error('gh down') } })
    await queue.approve(REPO, url(1), { attach: { url: url(1), queued: (e) => answers.push(e) } })
    expect(answers).toEqual([null])
    expect(w.runs).toEqual([])
    expect(store.forRepo(REPO).items).toHaveLength(1)
  })

  it('a corrupt queue file reads as empty and is rewritten cleanly', () => {
    writeFileSync(file, '{not json')
    const store = createQueueStore(file)
    expect(store.forRepo(REPO).items).toEqual([])
    store.add(REPO, url(3))
    expect(JSON.parse(readFileSync(file, 'utf-8')).repos[REPO].items[0].number).toBe(3)
  })
})

describe('outcomeFor', () => {
  it('merged, conflict (kept), sent back and refusals (left, with the first line that says why)', () => {
    expect(outcomeFor({ result: { merged: true } })).toEqual({ kind: 'merged' })
    expect(outcomeFor({ result: { reengaged: true, code: 'REBASE_CONFLICT' } }).kind).toBe('conflict')
    expect(outcomeFor({ body: { code: 'NOT_MERGEABLE', message: 'x' } }).kind).toBe('conflict')
    expect(outcomeFor({ result: { reengaged: true, code: 'CI_FAILED', reason: '**CI: failing checks**\n\ntests failed' } })).toMatchObject({ kind: 'failed', reason: 'CI_FAILED: tests failed' })
    expect(outcomeFor({ body: { code: 'MEMORY_PRESSURE', message: 'memory' } })).toMatchObject({ kind: 'failed', reason: 'memory' })
    expect(outcomeFor(undefined)).toMatchObject({ kind: 'failed', reason: 'the merge failed' })
  })
})

describe('answered-but-unbuilt facts', () => {
  it('only rows with no reply and no work commit since are MARVIN\'s unbuilt move', () => {
    expect(unbuiltFrom([{ url: 'a', addressed_by: null, built_since: false }, { url: 'b', addressed_by: 'reply', built_since: false },
      { url: 'c', addressed_by: null, built_since: true }, null, { addressed_by: null }])).toEqual(['a'])
    expect(unbuiltFrom('junk')).toEqual([])
  })

  it('the cache keeps its last answer when GitHub fails, and coalesces refreshes asked while one runs', async () => {
    let calls = 0
    let fail = false
    const exec = async () => { calls++; if (fail) throw new Error('down'); return { stdout: JSON.stringify([{ url: 'a', addressed_by: null, built_since: false }]) } }
    const c = createUnbuiltCache({ exec })
    await Promise.all([c.refresh(), c.refresh(), c.refresh()])
    expect(calls).toBe(2)                                      // one run, plus one more for the refreshes asked meanwhile
    expect([...c.get()]).toEqual(['a'])
    fail = true
    await c.refresh()
    expect([...c.get()]).toEqual(['a'])
  })
})

// marvin#1097: a temporary "not yet" keeps the PR queued, held until what it waits on changes. Before, every refusal
// but a conflict removed the PR and only an Approve brought it back (four stalls on 2026-11-03/04).
describe('temporary refusals hold, they never drop the PR', () => {
  const refuse = (code, message = code) => ({ body: { code, message } })
  const stored = () => createQueueStore(file).forRepo(REPO)

  it('outcomeFor sorts temporary refusals from real failures', () => {
    expect(outcomeFor(refuse('CI_PENDING'))).toMatchObject({ kind: 'hold', until: 'checks' })
    expect(outcomeFor(refuse('MAIN_RED'))).toMatchObject({ kind: 'hold', until: 'main' })
    for (const c of ['NO_UI_EVIDENCE', 'IMAGES_STALE', 'IMAGES_UNPINNED']) expect(outcomeFor(refuse(c))).toMatchObject({ kind: 'hold', until: 'head' })
    expect(outcomeFor(refuse('GATE_INFRA'))).toMatchObject({ kind: 'hold', until: 'later' })
    expect(outcomeFor(refuse('MEMORY_PRESSURE')).kind).toBe('failed')   // the memory queue resumes it (#940)
    for (const c of ['GATE_TESTS_FAILED', 'CI_FAILED', 'SENT_BACK', 'DECISIONS_PENDING', 'WRONG_BASE', 'PR_DRAFT']) expect(outcomeFor(refuse(c)).kind).toBe('failed')
    expect(outcomeFor({ result: { merged: false, code: 'GATE_TESTS_FAILED', reason: 'x' } }).kind).toBe('failed')
  })

  it('checks still running: the PR stays queued and merges by itself once they change, with no second Approve', async () => {
    const w = world([{ number: 1093 }])
    w.outcome = (n) => (w.prs.get(n).statusCheckRollup === green ? refuse('CI_PENDING', "GitHub's checks are still running: Secret scan") : { result: { merged: true } })
    const { queue } = make(w)
    await queue.approve(REPO, url(1093))
    expect(w.merged).toEqual([])
    expect(stored().items.map((i) => i.number)).toEqual([1093])
    expect(stored().failed[url(1093)]).toBeUndefined()
    expect(stored().items[0].hold).toMatchObject({ code: 'CI_PENDING', until: 'checks' })
    await queue.kick(REPO)                                   // nothing changed: still held, not retried
    expect(w.runs.length).toBe(1)
    w.prs.get(1093).statusCheckRollup = [{ __typename: 'CheckRun', name: 'Secret scan', status: 'COMPLETED', conclusion: 'SUCCESS' }]
    await queue.kick(REPO)                                   // the check watch's kick after the checks finished
    expect(w.merged).toEqual([1093])
  })

  it('a held PR is not retried in a loop within one pass', async () => {
    const w = world([{ number: 1 }])
    w.outcome = () => refuse('CI_PENDING')
    const { queue } = make(w)
    await queue.approve(REPO, url(1))
    expect(w.runs.length).toBe(1)
  })

  it('stale images: held until a new commit, then retried', async () => {
    const w = world([{ number: 2 }])
    w.outcome = (n) => (w.prs.get(n).headRefOid === 'sha2' ? refuse('IMAGES_STALE') : { result: { merged: true } })
    const { queue } = make(w)
    await queue.approve(REPO, url(2))
    await queue.kick(REPO)
    expect(w.runs.length).toBe(1)
    w.prs.get(2).headRefOid = 'sha2-new'
    await queue.kick(REPO)
    expect(w.merged).toEqual([2])
  })

  it('main red: held until main moves', async () => {
    let mainSha = 'main1'
    const w = world([{ number: 3 }])
    w.load = async () => ({ openPrs: enrichForOrder([...w.prs.values()].map((p) => ({ ...p })), { repo: REPO }), mainState: mainStateFrom({ headSha: mainSha }) })
    w.outcome = () => (mainSha === 'main1' ? refuse('MAIN_RED') : { result: { merged: true } })
    const { queue } = make(w)
    await queue.approve(REPO, url(3))
    await queue.kick(REPO)
    expect(w.runs.length).toBe(1)
    mainSha = 'main2'
    await queue.kick(REPO)
    expect(w.merged).toEqual([3])
  })

  it('infrastructure trouble: tried again on a later trigger, not before its back-off', async () => {
    let now = 1000
    const w = world([{ number: 4 }])
    w.outcome = () => (now < 1000 + 300_000 ? refuse('GATE_INFRA') : { result: { merged: true } })
    const { queue } = make(w, { clock: () => now })
    await queue.approve(REPO, url(4))
    await queue.kick(REPO)
    expect(w.runs.length).toBe(1)
    now += 300_001
    await queue.kick(REPO)
    expect(w.merged).toEqual([4])
  })

  it('a real failure still leaves the queue with its reason', async () => {
    const w = world([{ number: 5 }])
    w.outcome = () => ({ result: { merged: false, code: 'GATE_TESTS_FAILED', reason: 'Failing tests (1)' } })
    const { queue } = make(w)
    await queue.approve(REPO, url(5))
    expect(stored().items).toEqual([])
    expect(stored().failed[url(5)].code).toBe('GATE_TESTS_FAILED')
  })

  it("a held PR's line says what it waits for, and an Approve forces a fresh try", async () => {
    const w = world([{ number: 6 }])
    w.outcome = () => refuse('CI_PENDING', "GitHub's checks are still running: Secret scan")
    const { queue } = make(w)
    await queue.approve(REPO, url(6))
    await queue.kick(REPO)
    expect(queue.view(REPO).entries[url(6)]).toMatchObject({ state: 'waiting', queued: true })
    expect(queue.view(REPO).entries[url(6)].reason).toMatch(/checks/)
    await queue.approve(REPO, url(6))
    expect(w.runs.length).toBe(2)
  })

  it('stacked on a held PR: the child waits for it, and both merge once it clears', async () => {
    const w = world([{ number: 10 }, { number: 11, baseRefName: 'b10' }])
    w.outcome = (n) => (n === 10 && w.prs.get(10).statusCheckRollup === green ? refuse('CI_PENDING') : { result: { merged: true } })
    const { queue } = make(w)
    await queue.approve(REPO, url(11))
    await queue.approve(REPO, url(10))
    expect(w.merged).toEqual([])
    w.prs.get(10).statusCheckRollup = [{ __typename: 'CheckRun', name: 'x', status: 'COMPLETED', conclusion: 'SUCCESS' }]
    await queue.kick(REPO)
    expect(w.merged).toEqual([10, 11])
  })
})

// marvin#1184: a merge that failed for a temporary reason (GitHub's rate limit, a GitHub outage, the network, main
// moving mid-merge) stays queued and is tried again later. #1118 left the queue on 2026-11-09 for a rate limit and
// only the owner noticing brought it back.
describe('temporary failures stay queued and retry (#1184)', () => {
  const refuse = (code, message = code) => ({ body: { code, message } })
  const RATE = 'gh-gate: API rate limit: interactive call deferred, cooldown until 11:44 (burst)'

  it('outcomeFor holds every retryable code for later', () => {
    for (const c of ['RATE_LIMITED', 'GITHUB_OUTAGE', 'TRANSIENT_NETWORK', 'BASE_MOVED']) {
      expect(outcomeFor(refuse(c, 'x'))).toMatchObject({ kind: 'hold', until: 'later', code: c })
    }
    expect(outcomeFor({ result: { merged: false, code: 'RATE_LIMITED', reason: RATE } })).toMatchObject({ kind: 'hold', until: 'later' })
  })

  it('a rate-limited merge stays queued, and merges on a later trigger after the back-off', async () => {
    let now = 1000
    const w = world([{ number: 1118 }])
    w.outcome = () => (w.runs.length === 1 ? refuse('RATE_LIMITED', RATE) : { result: { merged: true } })
    const { queue, store } = make(w, { clock: () => now })
    await queue.approve(REPO, url(1118))
    const q = store.forRepo(REPO)
    expect(q.failed[url(1118)]).toBeUndefined()
    expect(q.items[0].hold).toMatchObject({ code: 'RATE_LIMITED', until: 'later', tries: 1 })
    await queue.kick(REPO)
    expect(w.runs.length).toBe(1)                      // not before its back-off
    now += 300_001
    await queue.kick(REPO)
    expect(w.merged).toEqual([1118])
  })

  it('the back-off honours a stated cooldown that ends later than the default', async () => {
    const at = new Date(2026, 10, 9, 11, 0, 0).getTime()
    const w = world([{ number: 2 }])
    w.outcome = () => refuse('RATE_LIMITED', RATE)
    const { queue, store } = make(w, { clock: () => at })
    await queue.approve(REPO, url(2))
    expect(store.forRepo(REPO).items[0].hold.notBefore).toBe(new Date(2026, 10, 9, 11, 44, 0).getTime())
  })

  it('a cooldown already past, or absurdly far off, falls back to the default back-off', async () => {
    const at = new Date(2026, 10, 9, 12, 0, 0).getTime()
    const w = world([{ number: 3 }])
    w.outcome = () => refuse('RATE_LIMITED', RATE)       // 11:44 is already past at 12:00
    const { queue, store } = make(w, { clock: () => at })
    await queue.approve(REPO, url(3))
    expect(store.forRepo(REPO).items[0].hold.notBefore).toBe(at + 300_000)
  })

  it('it keeps failing: after a bounded number of tries it leaves the queue with its reason', async () => {
    let now = 1000
    const w = world([{ number: 4 }])
    w.outcome = () => refuse('GITHUB_OUTAGE', 'remote: Internal Server Error')
    const { queue, store } = make(w, { clock: () => now })
    await queue.approve(REPO, url(4))
    for (let i = 0; i < 20; i++) { now += 3_600_001; await queue.kick(REPO) }
    expect(w.runs.length).toBe(6)
    expect(store.forRepo(REPO).items).toEqual([])
    expect(store.forRepo(REPO).failed[url(4)]).toMatchObject({ code: 'GITHUB_OUTAGE' })
    expect(store.forRepo(REPO).failed[url(4)].reason).toMatch(/6 tries/)
  })

  it('a different temporary failure after a hold starts its own count', async () => {
    let now = 1000
    const w = world([{ number: 5 }])
    const seq = ['RATE_LIMITED', 'RATE_LIMITED', 'TRANSIENT_NETWORK']
    w.outcome = () => (w.runs.length <= seq.length ? refuse(seq[w.runs.length - 1]) : { result: { merged: true } })
    const { queue, store } = make(w, { clock: () => now })
    await queue.approve(REPO, url(5))
    now += 3_600_001; await queue.kick(REPO)
    now += 3_600_001; await queue.kick(REPO)
    expect(store.forRepo(REPO).items[0].hold).toMatchObject({ code: 'TRANSIENT_NETWORK', tries: 1 })
    now += 3_600_001; await queue.kick(REPO)
    expect(w.merged).toEqual([5])
  })

  it('a real failure still leaves at once', async () => {
    const w = world([{ number: 6 }])
    w.outcome = () => ({ result: { merged: false, code: 'GATE_TESTS_FAILED', reason: 'Failing tests (1)' } })
    const { queue, store } = make(w)
    await queue.approve(REPO, url(6))
    expect(store.forRepo(REPO).failed[url(6)]).toBeTruthy()
  })
})

// marvin#1183: a PR held on a conflict waited from 2026-11-05 to 11-09 and nothing said so. After a day held on the
// same commit, the owner is told once; a new commit starts over.
describe('a conflict held too long is told once (#1183)', () => {
  const DAY = 24 * 60 * 60 * 1000
  it('tells once after a day on the same commit, never before, and again only for a new conflicting commit', async () => {
    let now = 1000
    const w = world([{ number: 942 }])
    w.outcome = () => ({ body: { code: 'NOT_MERGEABLE', message: 'conflicts with main' } })
    const told = []
    const { queue, store } = make(w, { clock: () => now, onStuck: (repo, pr, info) => told.push([pr.number, info.head]) })
    await queue.approve(REPO, url(942))
    expect(store.forRepo(REPO).items[0]).toMatchObject({ conflictHead: 'sha942', conflictAt: 1000 })
    now += DAY - 1
    await queue.kick(REPO)
    expect(told).toEqual([])
    now += 2
    await queue.kick(REPO)
    await queue.kick(REPO)
    expect(told).toEqual([[942, 'sha942']])                         // once, not every trigger
    w.prs.get(942).headRefOid = 'sha942b'                            // a new commit: tried again, conflicts again
    await queue.kick(REPO)
    expect(store.forRepo(REPO).items[0]).toMatchObject({ conflictHead: 'sha942b', conflictAt: now })
    now += DAY + 1
    await queue.kick(REPO)
    expect(told).toEqual([[942, 'sha942'], [942, 'sha942b']])
  })

  it('a telling that throws never stops the queue', async () => {
    let now = 1000
    const w = world([{ number: 1 }, { number: 2 }])
    w.outcome = (n) => (n === 1 ? { body: { code: 'NOT_MERGEABLE', message: 'x' } } : { result: { merged: true } })
    const { queue } = make(w, { clock: () => now, onStuck: () => { throw new Error('no notifier') } })
    await queue.approve(REPO, url(1))
    now += DAY + 1
    await queue.approve(REPO, url(2))
    expect(w.merged).toEqual([2])
  })
})

describe('resumeInterrupted', () => {
  it('resumes each lost merge by calling queue.approve with the repo from repoOf', async () => {
    const w = world([{ number: 100 }, { number: 101 }])
    const { queue, store } = make(w)
    const lost = [
      { url: url(100) },
      { url: url(101) }
    ]
    const repoOf = (u) => (String(u).includes('/pull/') ? REPO : null)
    const results = await resumeInterrupted(queue, lost, { repoOf })
    expect(results).toEqual([
      { url: url(100), resumed: true },
      { url: url(101), resumed: true }
    ])
    expect(store.forRepo(REPO).items).toHaveLength(2)
    expect(store.forRepo(REPO).items[0].url).toBe(url(100))
    expect(store.forRepo(REPO).items[1].url).toBe(url(101))
  })

  it('skips entries with no resolvable repo', async () => {
    const w = world([{ number: 100 }])
    const { queue, store } = make(w)
    const lost = [
      { url: url(100) },
      { url: 'https://example.com/invalid' }
    ]
    const repoOf = (u) => (String(u).includes('github.com') ? REPO : null)
    const results = await resumeInterrupted(queue, lost, { repoOf })
    expect(results).toEqual([
      { url: url(100), resumed: true },
      { url: 'https://example.com/invalid', resumed: false, reason: 'repo not resolvable' }
    ])
    expect(store.forRepo(REPO).items).toHaveLength(1)
  })

  it('uses the "by" parameter when approving', async () => {
    const w = world([{ number: 100 }])
    const { queue, store } = make(w)
    const lost = [{ url: url(100) }]
    const repoOf = () => REPO
    await resumeInterrupted(queue, lost, { repoOf, by: 'auto' })
    expect(store.forRepo(REPO).items[0].by).toBe('auto')
  })

  it('defaults "by" to "auto"', async () => {
    const w = world([{ number: 100 }])
    const { queue, store } = make(w)
    const lost = [{ url: url(100) }]
    const repoOf = () => REPO
    await resumeInterrupted(queue, lost, { repoOf })
    expect(store.forRepo(REPO).items[0].by).toBe('auto')
  })

  it('handles null or undefined lost gracefully', async () => {
    const w = world([{ number: 100 }])
    const { queue } = make(w)
    const repoOf = () => REPO
    const results1 = await resumeInterrupted(queue, null, { repoOf })
    const results2 = await resumeInterrupted(queue, undefined, { repoOf })
    expect(results1).toEqual([])
    expect(results2).toEqual([])
  })
})
