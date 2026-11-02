import { describe, it, expect } from 'vitest'
import { mergeOrder, mainStateFrom, enrichForOrder, closesRefs, ordinal } from '../webhook-server/merge_order.js'

// marvin#231: the merge queue's order and each PR's one line. These try to break it with the cases that broke the
// hand-merging on 2026-10-30 (stacked PRs, main red, answers not built) and with malformed input.
const REPO = 'G-Eskayo/marvin'
const url = (n) => `https://github.com/${REPO}/pull/${n}`
const green = [{ __typename: 'CheckRun', name: 'tests', status: 'COMPLETED', conclusion: 'SUCCESS' }]
const pr = (n, extra = {}) => ({ number: n, url: url(n), repo: REPO, title: `PR ${n}`, body: `Closes #${n + 1000}`,
  baseRefName: 'main', headRefName: `b${n}`, headRefOid: `sha${n}`, mergeable: 'MERGEABLE', statusCheckRollup: green, ...extra })
const q = (...ns) => ({ items: ns.map((n, i) => ({ url: url(n), approvedAt: 100 + i })), failed: {}, running: null })
const green_main = mainStateFrom({ issues: [] })
const line = (out, n) => out.entries[url(n)]

describe('mergeOrder: stacked PRs go base first', () => {
  // The real chain on 2026-10-30: #936 -> #941 -> #942, approved in reverse.
  const chain = [pr(936), pr(941, { baseRefName: 'b936' }), pr(942, { baseRefName: 'b941' })]

  it('approved #942, #941, #936 in that order: only #936 can go; the others wait for the PR they are built on', () => {
    const out = mergeOrder(chain, green_main, q(942, 941, 936))
    expect(out.next).toBe(url(936))
    expect(out.order).toEqual([url(936), url(941), url(942)])
    expect(line(out, 936).reason).toBe('queued · 1st · starts next')
    expect(line(out, 941)).toMatchObject({ state: 'waiting', tone: 'amber', reason: "waits for #936 (it's built on it)", waitsFor: 936, queued: true })
    expect(line(out, 942).reason).toBe("waits for #941 (it's built on it)")
  })

  it('a stacked PR that is not approved still says what it waits for, and is not queued', () => {
    const out = mergeOrder(chain, green_main, q())
    expect(line(out, 941)).toMatchObject({ queued: false, state: 'waiting', reason: "waits for #936 (it's built on it)" })
    expect(line(out, 936)).toMatchObject({ queued: false, state: 'ready', reason: null, tone: null })
    expect(out.next).toBeNull()
  })

  it('a base that failed in the queue is named with why, for every PR built on it', () => {
    const queue = { ...q(941), failed: { [url(936)]: { reason: 'GATE_TESTS_FAILED: test_box_trial' } } }
    const out = mergeOrder(chain, green_main, queue)
    expect(line(out, 941).reason).toBe('waits for #936 (it failed: GATE_TESTS_FAILED: test_box_trial)')
    expect(out.next).toBeNull()
  })

  it('a cycle in bases is said plainly, never loops, and never merges', () => {
    const loop = [pr(1, { baseRefName: 'b2' }), pr(2, { baseRefName: 'b1' }), pr(3)]
    const out = mergeOrder(loop, green_main, q(1, 2, 3))
    expect(line(out, 1).reason).toBe('its base PRs form a loop: #1 → #2 → #1')
    expect(line(out, 2).reason).toMatch(/its base PRs form a loop: #2 → #1 → #2|#1 → #2 → #1/)
    expect(out.next).toBe(url(3))
    expect(out.order).toHaveLength(3)
  })

  it('a PR whose own head is its base (a self-loop) is not taken for a stack on itself', () => {
    const out = mergeOrder([pr(5, { baseRefName: 'b5' })], green_main, q(5))
    expect(line(out, 5).reason).toBe('targets b5, which has no open PR · change its base to main')
    expect(out.next).toBeNull()
  })

  it('a base PR closed without merging leaves its child aimed at a branch no open PR has: it waits and says so', () => {
    const out = mergeOrder([pr(941, { baseRefName: 'b936' })], green_main, q(941))
    expect(line(out, 941).reason).toBe('targets b936, which has no open PR · change its base to main')
    expect(out.next).toBeNull()
  })
})

describe('mergeOrder: main is red', () => {
  const issues = [{ number: 978, title: 'Main is red at 9f4ac8d: fix forward', state: 'OPEN', labels: [{ name: 'main-red' }, { name: 'bug' }, { name: 'priority:p0' }] }]
  const red = mainStateFrom({ issues })

  it('only the PR that closes the main-red ticket goes, ahead of PRs approved earlier; the rest wait for it', () => {
    const prs = [pr(970), pr(971), pr(986, { body: 'Main green again.\n\nCloses #978' })]
    const out = mergeOrder(prs, red, q(970, 971, 986))
    expect(out.next).toBe(url(986))
    expect(line(out, 970).reason).toBe('main is red · waits for #986')
    expect(line(out, 971).reason).toBe('main is red · waits for #986')
    expect(line(out, 986).reason).toBe('queued · 1st · starts next')
  })

  it('with no fix PR open yet, the others wait for the ticket', () => {
    const out = mergeOrder([pr(970)], red, q(970))
    expect(line(out, 970).reason).toBe('main is red · waits for #978')
    expect(out.next).toBeNull()
  })

  it('a fix linked to an incident ticket, or a bug+p0 "Main red" one, also goes', () => {
    const incident = mainStateFrom({ issues: [...issues, { number: 990, title: 'Webhook down', labels: ['incident'] }] })
    expect(mergeOrder([pr(1, { body: 'Fixes #990' }), pr(2)], incident, q(2, 1)).next).toBe(url(1))
    const handFiled = mainStateFrom({ issues: [{ number: 991, title: 'Main red: vitest', labels: ['bug', 'priority:p0'] }] })
    expect(handFiled.red).toBe(true)
    expect(mergeOrder([pr(1, { body: 'Closes G-Eskayo/marvin#991' }), pr(2)], handFiled, q(2, 1)).next).toBe(url(1))
  })

  it('a ticket of another repo with the same number is not this repo\'s fix', () => {
    const out = mergeOrder([pr(1, { body: 'Closes G-Eskayo/clarity-captions#978' })], red, q(1))
    expect(line(out, 1).reason).toBe('main is red · waits for #978')
  })

  it('main-health red with no ticket still holds every PR', () => {
    const out = mergeOrder([pr(1)], mainStateFrom({ health: { ok: false, failed: ['x'] } }), q(1))
    expect(line(out, 1).reason).toBe('main is red · waits for a fix')
    expect(out.next).toBeNull()
  })

  it('a closed main-red ticket is green, and an incident alone does not make main red', () => {
    expect(mainStateFrom({ issues: [{ ...issues[0], state: 'CLOSED' }] }).red).toBe(false)
    expect(mainStateFrom({ issues: [{ number: 5, title: 'x', labels: ['incident'] }] }).red).toBe(false)
  })
})

describe('mergeOrder: a PR\'s own blockers come first', () => {
  it('answered-but-unbuilt Decisions: "your answers aren\'t built yet", even when it also waits on its base and main is red', () => {
    const issues = [{ number: 978, title: 'Main is red', labels: ['main-red'] }]
    const prs = enrichForOrder([pr(941), pr(942, { baseRefName: 'b941' })], { repo: REPO, unbuilt: new Set([url(941), url(942)]) })
    const out = mergeOrder(prs, mainStateFrom({ issues }), q(941, 942))
    expect(line(out, 941)).toMatchObject({ reason: "your answers aren't built yet", unbuilt: true, state: 'waiting' })
    expect(line(out, 942).reason).toBe("your answers aren't built yet")
    expect(out.next).toBeNull()
  })

  it('open Decisions count what waits for the owner, singular and plural', () => {
    const body = (n) => `## Decisions\n<!-- marvin:decisions -->\n${Array.from({ length: n }, (_, i) => `### q${i}: Which?\n- [ ] A\n- [ ] B\n`).join('')}`
    expect(line(mergeOrder([pr(1, { body: body(1) })], green_main, q(1)), 1).reason).toBe('1 Decision is waiting for you')
    expect(line(mergeOrder([pr(1, { body: body(3) })], green_main, q(1)), 1).reason).toBe('3 Decisions are waiting for you')
  })

  it('failing checks are named', () => {
    const red = [{ __typename: 'CheckRun', name: 'python-tests', status: 'COMPLETED', conclusion: 'FAILURE' }, ...green]
    expect(line(mergeOrder([pr(1, { statusCheckRollup: red })], green_main, q(1)), 1).reason).toBe('checks failing: python-tests')
  })

  it('a conflict after a merge says which merge, and whether the resolver can fix it or it needs a rebuild', () => {
    const rebaseStatus = { [url(972)]: { state: 'conflict', after: 970 } }
    let prs = enrichForOrder([pr(972, { mergeable: 'CONFLICTING' })], { repo: REPO, rebaseStatus })
    expect(line(mergeOrder(prs, green_main, q(972)), 972)).toMatchObject({ reason: 'conflicts with main after #970 · MARVIN is fixing it', conflict: true })
    prs = enrichForOrder([pr(972, { mergeable: 'CONFLICTING' })], { repo: REPO, rebaseStatus, repairFailed: { [`${REPO}#972`]: 'sha972' } })
    expect(line(mergeOrder(prs, green_main, q(972)), 972).reason).toBe('conflicts with main after #970 · needs a rebuild')
    // A repair that failed on an OLDER commit says nothing about this one.
    prs = enrichForOrder([pr(972, { mergeable: 'CONFLICTING' })], { repo: REPO, repairFailed: { [`${REPO}#972`]: 'old' } })
    expect(line(mergeOrder(prs, green_main, { ...q(972), lastMerged: 971 }), 972).reason).toBe('conflicts with main after #971 · MARVIN is fixing it')
  })

  it('a stale post-merge conflict is overruled once GitHub says the PR merges', () => {
    const prs = enrichForOrder([pr(972)], { repo: REPO, rebaseStatus: { [url(972)]: { state: 'conflict', after: 970 } } })
    expect(mergeOrder(prs, green_main, q(972)).next).toBe(url(972))
  })

  it('the gate\'s conflict on a commit holds that commit; a new commit (the resolver\'s push) is tried again', () => {
    const queue = { items: [{ url: url(5), approvedAt: 1, conflictHead: 'sha5' }], failed: {}, lastMerged: 4 }
    expect(line(mergeOrder([pr(5)], green_main, queue), 5).reason).toBe('conflicts with main after #4 · MARVIN is fixing it')
    expect(mergeOrder([pr(5, { headRefOid: 'new' })], green_main, queue).next).toBe(url(5))
  })

  it('a sent-back PR waits for its rework', () => {
    const prs = enrichForOrder([pr(1)], { repo: REPO, issues: [{ number: 1001, labels: ['needs-reengagement'] }] })
    expect(line(mergeOrder(prs, green_main, q(1)), 1).reason).toBe('sent back for rework')
  })
})

describe('mergeOrder: positions', () => {
  it('queued PRs go in approval order, each saying who it starts after', () => {
    const out = mergeOrder([pr(970), pr(971), pr(972)], green_main, q(971, 972, 970))
    expect(out.order).toEqual([url(971), url(972), url(970)])
    expect(line(out, 971).reason).toBe('queued · 1st · starts next')
    expect(line(out, 972)).toMatchObject({ reason: 'queued · 2nd · starts after #971', position: 2, tone: 'sky' })
    expect(line(out, 970).reason).toBe('queued · 3rd · starts after #972')
  })

  it('the merge running now is 1st and nothing else starts; blocked PRs are skipped in the count', () => {
    const red = [{ __typename: 'CheckRun', name: 't', status: 'COMPLETED', conclusion: 'FAILURE' }]
    const out = mergeOrder([pr(970), pr(971, { statusCheckRollup: red }), pr(972)], green_main, { ...q(970, 971, 972), running: url(970) })
    expect(line(out, 970)).toMatchObject({ state: 'running', reason: 'merging now', position: 1 })
    expect(line(out, 972).reason).toBe('queued · 2nd · starts after #970')
    expect(line(out, 971).position).toBeNull()
    expect(out.next).toBeNull()
  })

  it('an empty queue, no PRs, junk input: nothing to do and nothing thrown', () => {
    expect(mergeOrder([], green_main, q())).toEqual({ entries: {}, order: [], next: null, dropped: [] })
    expect(mergeOrder(null, null, null).next).toBeNull()
    expect(mergeOrder([null, { number: 1 }, pr(2)], undefined, { items: [null, { url: 7 }] }).entries[url(2)].state).toBe('ready')
  })

  it('a queued PR that is no longer open is dropped; one queued twice counts once at its first time', () => {
    const queue = { items: [{ url: url(1), approvedAt: 5 }, { url: url(9), approvedAt: 1 }, { url: url(1), approvedAt: 0 }], failed: {} }
    const out = mergeOrder([pr(1), pr(2)], green_main, { ...queue, items: [...queue.items, { url: url(2), approvedAt: 3 }] })
    expect(out.dropped).toEqual([url(9)])
    expect(out.order).toEqual([url(2), url(1)])
  })

  it('ordinals', () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111].map(ordinal)).toEqual(['1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '101st', '111th'])
  })

  it('closesRefs reads every keyword form once, and skips other repos', () => {
    expect(closesRefs('Closes #1, fixes #2. Resolved G-Eskayo/marvin#3 and closes other/repo#4; Fixes #1', REPO)).toEqual([1, 2, 3])
  })
})
