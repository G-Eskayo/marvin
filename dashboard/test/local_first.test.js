import { describe, it, expect, vi } from 'vitest'
import { createGithubState } from '../electron/main/github_state.js'
import { createLocalFirst, coalesce, createIssueReader, createRepoHeadCheck, decisionsDisagreement, sentBackDisagreement, apiBase } from '../electron/main/local_first.js'

// The real gate's state on this Mac must never decide a test.
process.env.MARVIN_GH_GATE_STATE = '/nonexistent/gh-gate.json'

const BODY = `Summary.

## Decisions
<!-- marvin:decisions -->
### dance: Which launch animation?
- [ ] A: Clap
- [ ] B: Bubble
`
const ANSWERED = BODY.replace('- [ ] B: Bubble', '- [x] B: Bubble')
const deferred = () => { let resolve, reject; const p = new Promise((a, b) => { resolve = a; reject = b }); return { p, resolve, reject } }

async function seeded(prs = [{ number: 7, url: 'https://github.com/o/r/pull/7', body: BODY, repo: undefined }], issues = []) {
  const state = createGithubState({ now: () => 0 })
  await state.get('prs', 'o/r', async () => prs)
  await state.get('prs-light', 'o/r', async () => prs.map(({ number, url }) => ({ number, url })))
  await state.get('board', 'o/r', async () => ({ issues, prs: [], holdComments: {} }))
  return state
}
const prsOf = (state) => state.get('prs', 'o/r', async () => { throw new Error('must come from memory') })
const boardOf = (state) => state.get('board', 'o/r', async () => { throw new Error('must come from memory') })

describe('createLocalFirst: an action shows its true result at once, then GitHub confirms it in the background', () => {
  it('applies the written body to the remembered PR, with no GitHub read', async () => {
    const state = await seeded()
    const lf = createLocalFirst({ state, readIssue: vi.fn(), onCorrected: vi.fn() })
    lf.setPrBody('o/r', 7, ANSWERED)
    expect((await prsOf(state))[0].body).toBe(ANSWERED)
  })

  it('GitHub confirms with a 304: nothing changes and nobody is told anything', async () => {
    const state = await seeded()
    const onCorrected = vi.fn()
    const readIssue = vi.fn(async () => ({ status: 304 }))
    const lf = createLocalFirst({ state, readIssue, onCorrected })
    const ver = lf.setPrBody('o/r', 7, ANSWERED)
    const r = await lf.confirmBody('o/r', 7, { ver, etag: 'W/"1"', body: ANSWERED })
    expect(r.status).toBe('confirmed')
    expect(readIssue).toHaveBeenCalledWith('o/r', 7, 'W/"1"')
    expect(onCorrected).not.toHaveBeenCalled()
  })

  it('GitHub returns different answers than the ones written: the view takes GitHub\'s and says so plainly', async () => {
    const state = await seeded()
    const onCorrected = vi.fn()
    const lf = createLocalFirst({ state, readIssue: async () => ({ status: 200, issue: { body: BODY, state: 'open', labels: [] } }), onCorrected })
    const ver = lf.setPrBody('o/r', 7, ANSWERED)
    const r = await lf.confirmBody('o/r', 7, { ver, body: ANSWERED })
    expect(r.status).toBe('corrected')
    expect((await prsOf(state))[0].body).toBe(BODY)
    expect(onCorrected).toHaveBeenCalledTimes(1)
    const msg = onCorrected.mock.calls[0][0]
    expect(msg).toMatchObject({ repo: 'o/r', number: 7, url: 'https://github.com/o/r/pull/7' })
    expect(msg.message).toMatch(/GitHub/)
    expect(msg.message).toMatch(/Which launch animation\?/)
  })

  it('GitHub changed other text but has the same answers: the body is updated quietly, no alarm', async () => {
    const state = await seeded()
    const onCorrected = vi.fn()
    const edited = ANSWERED.replace('Summary.', 'Summary, edited on GitHub.')
    const lf = createLocalFirst({ state, readIssue: async () => ({ status: 200, issue: { body: edited, state: 'open', labels: [] } }), onCorrected })
    const ver = lf.setPrBody('o/r', 7, ANSWERED)
    expect((await lf.confirmBody('o/r', 7, { ver, body: ANSWERED })).status).toBe('updated')
    expect((await prsOf(state))[0].body).toBe(edited)
    expect(onCorrected).not.toHaveBeenCalled()
  })

  it('a slow confirm that arrives after a newer local write never overwrites it', async () => {
    const state = await seeded()
    const onCorrected = vi.fn()
    const slow = deferred()
    const lf = createLocalFirst({ state, readIssue: () => slow.p, onCorrected })
    const v1 = lf.setPrBody('o/r', 7, ANSWERED)
    const confirming = lf.confirmBody('o/r', 7, { ver: v1, body: ANSWERED })
    const newer = BODY.replace('- [ ] A: Clap', '- [x] A: Clap')
    lf.setPrBody('o/r', 7, newer) // a second answer, written before the first confirm came back
    slow.resolve({ status: 200, issue: { body: ANSWERED, state: 'open', labels: [] } })
    expect((await confirming).status).toBe('superseded')
    expect((await prsOf(state))[0].body).toBe(newer)
    expect(onCorrected).not.toHaveBeenCalled()
  })

  it('offline while confirming: keeps the written result (GitHub already accepted it) and stays quiet', async () => {
    const state = await seeded()
    const onCorrected = vi.fn()
    const lf = createLocalFirst({ state, readIssue: async () => { throw new Error('getaddrinfo ENOTFOUND api.github.com') }, onCorrected })
    const ver = lf.setPrBody('o/r', 7, ANSWERED)
    expect((await lf.confirmBody('o/r', 7, { ver, body: ANSWERED })).status).toBe('unconfirmed')
    expect((await prsOf(state))[0].body).toBe(ANSWERED)
    expect(onCorrected).not.toHaveBeenCalled()
  })

  it('a garbled confirm answer is not a disagreement', async () => {
    const state = await seeded()
    const onCorrected = vi.fn()
    const lf = createLocalFirst({ state, readIssue: async () => ({ status: 200, issue: null }), onCorrected })
    const ver = lf.setPrBody('o/r', 7, ANSWERED)
    expect((await lf.confirmBody('o/r', 7, { ver, body: ANSWERED })).status).toBe('unconfirmed')
    expect(onCorrected).not.toHaveBeenCalled()
  })

  it('a merged PR leaves the list at once; GitHub still showing it open puts it back and says so', async () => {
    const state = await seeded()
    const onCorrected = vi.fn()
    const lf = createLocalFirst({ state, readIssue: async () => ({ status: 200, issue: { body: BODY, state: 'open', labels: [] } }), onCorrected })
    const ver = lf.removePr('o/r', 7)
    expect(await prsOf(state)).toEqual([])
    expect(await state.get('prs-light', 'o/r', async () => { throw new Error('memory') })).toEqual([])
    const r = await lf.confirmClosed('o/r', 7, { ver, url: 'https://github.com/o/r/pull/7', verb: 'merged' })
    expect(r.status).toBe('corrected')
    expect(onCorrected.mock.calls[0][0].message).toMatch(/still shows #7 open/)
    // put back means: this repo is re-read on the next look, not every repo
    let reads = 0
    await state.get('prs', 'o/r', async () => { reads += 1; return [{ number: 7 }] })
    await state.get('prs', 'o/other', async () => { reads += 1; return [] })
    expect(reads).toBe(2)
    await state.get('prs', 'o/other', async () => { reads += 1; return [] })
    expect(reads).toBe(2)
  })

  it('a merged PR that GitHub shows closed is confirmed', async () => {
    const state = await seeded()
    const onCorrected = vi.fn()
    const lf = createLocalFirst({ state, readIssue: async () => ({ status: 200, issue: { state: 'closed', labels: [] } }), onCorrected })
    const ver = lf.removePr('o/r', 7)
    expect((await lf.confirmClosed('o/r', 7, { ver, url: 'u', verb: 'merged' })).status).toBe('confirmed')
    expect(onCorrected).not.toHaveBeenCalled()
  })

  it('sending a ticket back marks it at once; GitHub not showing the label reverts it and says so', async () => {
    const state = await seeded(undefined, [{ number: 3, state: 'OPEN', labels: [{ name: 'ready-for-agent' }] }])
    const onCorrected = vi.fn()
    const lf = createLocalFirst({ state, readIssue: async () => ({ status: 200, issue: { state: 'open', labels: [{ name: 'ready-for-agent' }] } }), onCorrected })
    const ver = lf.setTicketLabel('o/r', 3, 'needs-reengagement', true)
    expect((await boardOf(state)).issues[0].labels.map((l) => l.name)).toContain('needs-reengagement')
    const r = await lf.confirmLabel('o/r', 3, { ver, label: 'needs-reengagement', present: true, url: 'https://github.com/o/r/pull/7' })
    expect(r.status).toBe('corrected')
    expect((await boardOf(state)).issues[0].labels.map((l) => l.name)).not.toContain('needs-reengagement')
    expect(onCorrected.mock.calls[0][0].message).toMatch(/#3/)
  })

  it('clearing the sent-back label removes it at once and is confirmed by GitHub', async () => {
    const state = await seeded(undefined, [{ number: 3, state: 'OPEN', labels: [{ name: 'needs-reengagement' }] }])
    const lf = createLocalFirst({ state, readIssue: async () => ({ status: 200, issue: { state: 'open', labels: [] } }), onCorrected: vi.fn() })
    const ver = lf.setTicketLabel('o/r', 3, 'needs-reengagement', false)
    expect((await boardOf(state)).issues[0].labels).toEqual([])
    expect((await lf.confirmLabel('o/r', 3, { ver, label: 'needs-reengagement', present: false })).status).toBe('confirmed')
  })

  it('two rapid writes to the same PR run one after the other, never interleaved', async () => {
    const state = await seeded()
    const lf = createLocalFirst({ state, readIssue: vi.fn(), onCorrected: vi.fn() })
    const order = []
    const first = deferred()
    const a = lf.serialize('o/r#7', async () => { order.push('a start'); await first.p; order.push('a end'); return 'a' })
    const b = lf.serialize('o/r#7', async () => { order.push('b start'); return 'b' })
    await Promise.resolve()
    expect(order).toEqual(['a start'])
    first.resolve()
    expect(await Promise.all([a, b])).toEqual(['a', 'b'])
    expect(order).toEqual(['a start', 'a end', 'b start'])
  })

  it('a failed write does not block the next one on the same PR', async () => {
    const lf = createLocalFirst({ state: createGithubState(), readIssue: vi.fn(), onCorrected: vi.fn() })
    await expect(lf.serialize('k', async () => { throw new Error('GitHub said no') })).rejects.toThrow('GitHub said no')
    expect(await lf.serialize('k', async () => 'next')).toBe('next')
  })

  it('writes to different PRs do not wait on each other', async () => {
    const lf = createLocalFirst({ state: createGithubState(), readIssue: vi.fn(), onCorrected: vi.fn() })
    const hold = deferred()
    lf.serialize('o/r#1', () => hold.p)
    expect(await lf.serialize('o/r#2', async () => 'free')).toBe('free')
    hold.resolve()
  })
})

describe('decisionsDisagreement: what GitHub has that differs from what was written, in plain words', () => {
  it('same answers: none', () => {
    expect(decisionsDisagreement(ANSWERED, ANSWERED)).toBeNull()
    expect(decisionsDisagreement(ANSWERED, ANSWERED.replace('Summary.', 'Other text.'))).toBeNull()
  })
  it('names the question and what GitHub shows', () => {
    const m = decisionsDisagreement(ANSWERED, BODY)
    expect(m).toMatch(/Which launch animation\?/)
    expect(m).toMatch(/no answer/)
    expect(decisionsDisagreement(ANSWERED, BODY.replace('- [ ] A: Clap', '- [x] A: Clap'))).toMatch(/A: Clap/)
  })
  it('the Decisions section gone on GitHub', () => {
    expect(decisionsDisagreement(ANSWERED, 'rewritten')).toMatch(/no longer has a Decisions section/)
  })
  it('junk in, no throw', () => {
    expect(() => decisionsDisagreement(null, undefined)).not.toThrow()
  })
})

describe('sentBackDisagreement', () => {
  it('only when the label is not where the write put it', () => {
    expect(sentBackDisagreement({ labels: [{ name: 'needs-reengagement' }] }, 'needs-reengagement', true)).toBe(false)
    expect(sentBackDisagreement({ labels: [] }, 'needs-reengagement', true)).toBe(true)
    expect(sentBackDisagreement({ labels: ['needs-reengagement'] }, 'needs-reengagement', false)).toBe(true)
  })
})

describe('coalesce: overlapping callers share one read', () => {
  it('three overlapping list calls make one read (2026-10-21: three ran at once, 17 s, 35 s and 43 s)', async () => {
    let reads = 0
    const hold = deferred()
    const list = coalesce(async () => { reads += 1; await hold.p; return reads }, () => 0)
    const all = Promise.all([list(), list(), list()])
    hold.resolve()
    expect(await all).toEqual([1, 1, 1])
    expect(reads).toBe(1)
  })
  it('a caller after a local write does not get an answer built before it', async () => {
    let version = 0
    let reads = 0
    const hold = deferred()
    const list = coalesce(async () => { reads += 1; const v = version; if (reads === 1) await hold.p; return v }, () => version)
    const old = list()
    version = 1
    const fresh = list()
    hold.resolve()
    expect(await old).toBe(0)
    expect(await fresh).toBe(1)
    expect(reads).toBe(2)
  })
  it('a failed read is not remembered: the next call tries again', async () => {
    let n = 0
    const list = coalesce(async () => { n += 1; if (n === 1) throw new Error('offline'); return 'ok' }, () => 0)
    await expect(list()).rejects.toThrow('offline')
    expect(await list()).toBe('ok')
  })
})

describe('createIssueReader: one conditional GET, the gh_watch.js ETag pattern', () => {
  const res = (status, body, etag) => ({ status, headers: { get: (h) => (h.toLowerCase() === 'etag' ? etag : null) }, json: async () => body })
  it('sends If-None-Match and the shared token; a 304 is free and carries no body', async () => {
    const fetch = vi.fn(async () => res(304, null, 'W/"1"'))
    const read = createIssueReader({ GH_TOKEN: 't' }, fetch)
    expect(await read('o/r', 7, 'W/"1"')).toEqual({ status: 304, etag: 'W/"1"' })
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toBe('https://api.github.com/repos/o/r/issues/7')
    expect(opts.headers['If-None-Match']).toBe('W/"1"')
    expect(opts.headers.Authorization).toBe('Bearer t')
  })
  it('a 200 returns the issue and its new etag', async () => {
    const read = createIssueReader({}, async () => res(200, { body: 'b', state: 'open' }, 'W/"2"'))
    expect(await read('o/r', 7)).toEqual({ status: 200, etag: 'W/"2"', issue: { body: 'b', state: 'open' } })
  })
  it('anything else (401, 404, 500) is an error, not a disagreement', async () => {
    const read = createIssueReader({}, async () => res(502, null))
    await expect(read('o/r', 7)).rejects.toThrow(/502/)
  })
  it('refuses a malformed repo or number before any request', async () => {
    const fetch = vi.fn()
    const read = createIssueReader({}, fetch)
    await expect(read('../etc', 7)).rejects.toThrow()
    await expect(read('o/r', 'x')).rejects.toThrow()
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('createRepoHeadCheck: is the remembered PR list of one repo still what GitHub has (for Approve)?', () => {
  const pull = (number, sha, base = 'main') => ({ number, head: { sha }, base: { ref: base } })
  const res = (status, body, etag) => ({ status, headers: { get: (h) => (h.toLowerCase() === 'etag' ? etag : null) }, json: async () => body })
  const cached = [{ number: 1, headRefOid: 'a', baseRefName: 'main' }, { number: 2, headRefOid: 'b', baseRefName: 'main' }]

  it('same PRs, same heads, same bases: fresh, and the next check is a free 304', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(res(200, [pull(2, 'b'), pull(1, 'a')], 'W/"e1"'))
      .mockResolvedValueOnce(res(304, null, 'W/"e1"'))
    const check = createRepoHeadCheck({}, fetch)
    expect(await check('o/r', cached)).toEqual({ fresh: true })
    expect(await check('o/r', cached)).toEqual({ fresh: true })
    expect(fetch.mock.calls[1][1].headers['If-None-Match']).toBe('W/"e1"')
  })
  it('a new push, a new PR, a closed PR or a changed base: stale', async () => {
    for (const pulls of [[pull(1, 'a'), pull(2, 'NEW')], [pull(1, 'a'), pull(2, 'b'), pull(3, 'c')], [pull(1, 'a')], [pull(1, 'a', 'dev'), pull(2, 'b')]]) {
      const check = createRepoHeadCheck({}, async () => res(200, pulls, 'W/"x"'))
      expect((await check('o/r', cached)).fresh).toBe(false)
    }
  })
  it('a 304 against an etag that never matched the remembered list is not taken as fresh', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(res(200, [pull(1, 'NEW'), pull(2, 'b')], 'W/"e1"'))
      .mockResolvedValueOnce(res(304, null, 'W/"e1"'))
    const check = createRepoHeadCheck({}, fetch)
    expect((await check('o/r', cached)).fresh).toBe(false)
    expect((await check('o/r', cached)).fresh).toBe(false)
  })
  it('offline or refused: stale (re-read that one repo), never a pass on faith', async () => {
    const check = createRepoHeadCheck({}, async () => { throw new Error('offline') })
    expect((await check('o/r', cached)).fresh).toBe(false)
  })
  it('more than one page of open PRs: cannot tell from one page, so stale', async () => {
    const many = Array.from({ length: 100 }, (_, i) => pull(i + 1, 's'))
    const check = createRepoHeadCheck({}, async () => res(200, many, 'W/"x"'))
    expect((await check('o/r', many.map((p) => ({ number: p.number, headRefOid: 's', baseRefName: 'main' })))).fresh).toBe(false)
  })
})

describe('apiBase: the token only ever goes to GitHub or to this machine', () => {
  it('defaults to GitHub; a local sandbox may override it; nothing else may', () => {
    expect(apiBase({})).toBe('https://api.github.com')
    expect(apiBase({ MARVIN_GITHUB_API: 'http://127.0.0.1:5123/' })).toBe('http://127.0.0.1:5123')
    expect(apiBase({ MARVIN_GITHUB_API: 'http://localhost:9' })).toBe('http://localhost:9')
    for (const bad of ['https://evil.example', 'http://127.0.0.1.evil.example', 'http://evil@127.0.0.2', 'file:///etc/passwd', 'javascript:alert(1)', 'not a url', 'http://[::1]:80']) {
      expect(apiBase({ MARVIN_GITHUB_API: bad })).toBe('https://api.github.com')
    }
  })
  it('the readers use it', async () => {
    const fetch = vi.fn(async () => ({ status: 304, headers: { get: () => null } }))
    await createIssueReader({ MARVIN_GITHUB_API: 'http://127.0.0.1:7' }, fetch)('o/r', 1, 'e')
    expect(fetch.mock.calls[0][0]).toBe('http://127.0.0.1:7/repos/o/r/issues/1')
  })
})
