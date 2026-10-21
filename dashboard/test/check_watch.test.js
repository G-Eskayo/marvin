import { describe, it, expect, vi } from 'vitest'
import { createCheckWatcher, startCheckWatch, createCheckProbe, checkRunsEndpoint, combinedStatusEndpoint, checksDigest, statusesDigest } from '../webhook-server/gh_watch.js'
import { pendingCheckHeads, prListArgs } from '../electron/main/mr_repos.js'

// marvin#555 (replaces #554's 90 s re-read): while a PR's checks run, ask GitHub "did this commit's checks change?" with an
// ETag on the change watch's ~20 s tick. A 304 is free; only a real change re-reads that repo's PR list.
const run = (name, status, conclusion = null) => ({ __typename: 'CheckRun', name, status, conclusion, workflowName: 'CI' })
const pr = (number, sha, rollup) => ({ number, headRefOid: sha, statusCheckRollup: rollup })
const head = (repo, sha, checkRuns = 'd0', statuses = null) => ({ repo, sha, checkRuns, statuses })

function scripted(answers) {
  const calls = []
  const probe = vi.fn(async (q) => {
    calls.push(q)
    const a = answers.shift()
    if (a instanceof Error) throw a
    return typeof a === 'function' ? a(q) : a
  })
  return { probe, calls }
}

describe('createCheckWatcher', () => {
  it('a 304 keeps everything as it is, sends the stored etag, and still counts as a check', async () => {
    let t = 1000
    const { probe, calls } = scripted([{ status: 200, etag: 'e1', digest: 'd0' }, { status: 304 }])
    const onChange = vi.fn()
    const w = createCheckWatcher({ probe, onChange, now: () => t })
    await w.tick([head('o/r', 'abc')])
    t = 21_000
    await w.tick([head('o/r', 'abc')])
    expect(onChange).not.toHaveBeenCalled()
    expect(calls.map((c) => [c.kind, c.repo, c.sha, c.etag])).toEqual([['check-runs', 'o/r', 'abc', undefined], ['check-runs', 'o/r', 'abc', 'e1']])
    expect(w.checkedAt('o/r', 'abc')).toBe(21_000)
  })

  it('a 200 whose checks differ from what the list showed re-reads that repo, once', async () => {
    const { probe } = scripted([{ status: 200, etag: 'e1', digest: 'd0' }, { status: 200, etag: 'e2', digest: 'd1' }])
    const onChange = vi.fn()
    const w = createCheckWatcher({ probe, onChange })
    await w.tick([head('o/r', 'abc')])
    await w.tick([head('o/r', 'abc')])
    expect(onChange.mock.calls).toEqual([['o/r']])
  })

  it('a 200 with the same checks (only the etag moved) does not re-read', async () => {
    const { probe } = scripted([{ status: 200, etag: 'e1', digest: 'd0' }, { status: 200, etag: 'e2', digest: 'd0' }])
    const onChange = vi.fn()
    const w = createCheckWatcher({ probe, onChange })
    await w.tick([head('o/r', 'abc')])
    await w.tick([head('o/r', 'abc')])
    expect(onChange).not.toHaveBeenCalled()
  })

  it('the very first answer already differing (a check finished between the list read and the probe) re-reads', async () => {
    const { probe } = scripted([{ status: 200, etag: 'e1', digest: 'all-done' }])
    const onChange = vi.fn()
    await createCheckWatcher({ probe, onChange }).tick([head('o/r', 'abc', 'still-running')])
    expect(onChange).toHaveBeenCalledWith('o/r')
  })

  it('a new push mid-run: the old commit is dropped (its etag forgotten) and the new one probed fresh', async () => {
    const { probe, calls } = scripted([{ status: 200, etag: 'old', digest: 'd0' }, { status: 200, etag: 'new', digest: 'd0' }, { status: 200, etag: 'x', digest: 'd0' }])
    const w = createCheckWatcher({ probe, onChange: vi.fn() })
    await w.tick([head('o/r', 'sha1')])
    await w.tick([head('o/r', 'sha2')])
    expect(calls[1]).toMatchObject({ sha: 'sha2', etag: undefined })
    expect(w.checkedAt('o/r', 'sha1')).toBe(null)
    await w.tick([head('o/r', 'sha1')]) // pushed back: treated as never seen
    expect(calls[2]).toMatchObject({ sha: 'sha1', etag: undefined })
  })

  it('offline or refused: keeps the etag, does not fire, and does not claim it checked', async () => {
    let t = 5
    const { probe, calls } = scripted([{ status: 200, etag: 'e1', digest: 'd0' }, new Error('offline'), { status: 403 }, { status: 304 }])
    const onChange = vi.fn()
    const w = createCheckWatcher({ probe, onChange, now: () => t })
    await w.tick([head('o/r', 'abc')])
    t = 10
    await expect(w.tick([head('o/r', 'abc')])).resolves.toBeUndefined()
    t = 15
    await w.tick([head('o/r', 'abc')])
    expect(w.checkedAt('o/r', 'abc')).toBe(5)
    t = 20
    await w.tick([head('o/r', 'abc')])
    expect(calls.map((c) => c.etag)).toEqual([undefined, 'e1', 'e1', 'e1'])
    expect(onChange).not.toHaveBeenCalled()
    expect(w.checkedAt('o/r', 'abc')).toBe(20)
  })

  it('a probe answering junk (no status, a 200 without etag) is ignored, never a throw', async () => {
    const { probe } = scripted([undefined, { status: 200 }, { status: 200, digest: 'other' }])
    const onChange = vi.fn()
    const w = createCheckWatcher({ probe, onChange })
    await w.tick([head('o/r', 'a')])
    await w.tick([head('o/r', 'a')])
    await w.tick([head('o/r', 'a')])
    expect(onChange).toHaveBeenCalledTimes(1) // a changed answer still counts even if GitHub sent no etag
  })

  it('PR closed (or its checks finished) mid-watch: stops probing that commit and forgets it', async () => {
    const { probe } = scripted([{ status: 200, etag: 'e1', digest: 'd0' }])
    const w = createCheckWatcher({ probe, onChange: vi.fn() })
    await w.tick([head('o/r', 'abc')])
    await w.tick([])
    await w.tick([])
    expect(probe).toHaveBeenCalledTimes(1)
    expect(w.checkedAt('o/r', 'abc')).toBe(null)
    expect(w.size()).toBe(0)
  })

  it('many pending PRs: one probe per commit per tick, and at most one re-read per repo per tick', async () => {
    const { probe } = scripted(Array.from({ length: 20 }, () => ({ status: 200, etag: 'e', digest: 'changed' })))
    const onChange = vi.fn()
    const w = createCheckWatcher({ probe, onChange })
    const heads = [head('o/r', 's1'), head('o/r', 's1'), head('o/r', 's2'), head('o/r', 's3'), head('o/x', 's9')]
    await w.tick(heads)
    expect(probe).toHaveBeenCalledTimes(4)
    expect(onChange.mock.calls).toEqual([['o/r'], ['o/x']])
  })

  it('a repo using commit statuses also probes the combined status, and only then', async () => {
    const { probe, calls } = scripted([{ status: 304 }, { status: 200, etag: 's', digest: 'st1' }])
    const onChange = vi.fn()
    const w = createCheckWatcher({ probe, onChange })
    await w.tick([head('o/r', 'abc', 'd0', 'st0')])
    expect(calls.map((c) => c.kind)).toEqual(['check-runs', 'status'])
    expect(onChange).toHaveBeenCalledWith('o/r')
    const only = scripted([{ status: 304 }])
    await createCheckWatcher({ probe: only.probe, onChange }).tick([head('o/r', 'abc', null, 'st0')])
    expect(only.calls.map((c) => c.kind)).toEqual(['status'])
  })

  it('junk heads (no repo or sha) are skipped', async () => {
    const { probe } = scripted([])
    await createCheckWatcher({ probe, onChange: vi.fn() }).tick([null, { repo: 'o/r' }, { sha: 'a' }, head('', 'a')])
    expect(probe).not.toHaveBeenCalled()
  })
})

describe('startCheckWatch', () => {
  it('ticks on an interval, never stacks a slow tick, and skips while the GitHub gate cools down', async () => {
    let fire
    const setIntervalFn = vi.fn((fn) => { fire = fn; return 1 })
    let release
    const probe = vi.fn(() => new Promise((r) => { release = () => r({ status: 304 }) }))
    let cooling = false
    startCheckWatch({ getHeads: () => [head('o/r', 'a')], probe, onChange: vi.fn(), intervalMs: 20_000, setIntervalFn, skip: () => cooling })
    expect(setIntervalFn.mock.calls[0][1]).toBe(20_000)
    await Promise.resolve()
    expect(probe).toHaveBeenCalledTimes(1)
    fire() // still running: ignored
    expect(probe).toHaveBeenCalledTimes(1)
    release()
    await new Promise((r) => setTimeout(r, 0))
    cooling = true
    fire()
    await Promise.resolve()
    expect(probe).toHaveBeenCalledTimes(1)
  })

  it('a getHeads that throws does not kill the watch', async () => {
    let fire
    let bad = true
    const probe = vi.fn(async () => ({ status: 304 }))
    startCheckWatch({ getHeads: () => { if (bad) throw new Error('no cache'); return [head('o/r', 'a')] }, probe, onChange: vi.fn(), setIntervalFn: (fn) => { fire = fn } })
    await new Promise((r) => setTimeout(r, 0))
    bad = false
    await fire()
    expect(probe).toHaveBeenCalledTimes(1)
  })
})

describe('createCheckProbe: the real conditional request', () => {
  const resp = (status, body, etag) => ({ status, headers: { get: (h) => (h.toLowerCase() === 'etag' ? etag : null) }, json: async () => body })

  it('asks the check-runs endpoint with If-None-Match and digests the answer like the PR list does', async () => {
    const doFetch = vi.fn(async () => resp(200, { check_runs: [{ name: 'tests', status: 'in_progress', conclusion: null }] }, 'W/"e2"'))
    const probe = createCheckProbe({ GH_TOKEN: 't' }, doFetch)
    const r = await probe({ kind: 'check-runs', repo: 'o/r', sha: 'abc', etag: 'W/"e1"' })
    expect(doFetch.mock.calls[0][0]).toBe(checkRunsEndpoint('o/r', 'abc'))
    expect(doFetch.mock.calls[0][1].headers).toMatchObject({ 'If-None-Match': 'W/"e1"', Authorization: 'Bearer t' })
    expect(r).toEqual({ status: 200, etag: 'W/"e2"', digest: checksDigest([run('tests', 'IN_PROGRESS')]) })
  })

  it('a 304 is passed through without reading a body', async () => {
    const json = vi.fn()
    const probe = createCheckProbe({}, async () => ({ status: 304, headers: { get: () => null }, json }))
    expect(await probe({ kind: 'check-runs', repo: 'o/r', sha: 'a', etag: 'x' })).toEqual({ status: 304, etag: undefined, digest: undefined })
    expect(json).not.toHaveBeenCalled()
  })

  it('the combined status endpoint is digested like the list\'s commit statuses', async () => {
    const doFetch = vi.fn(async () => resp(200, { statuses: [{ context: 'ci/x', state: 'pending' }] }, 'e'))
    const r = await createCheckProbe({}, doFetch)({ kind: 'status', repo: 'o/r', sha: 'abc' })
    expect(doFetch.mock.calls[0][0]).toBe(combinedStatusEndpoint('o/r', 'abc'))
    expect(r.digest).toBe(statusesDigest([{ __typename: 'StatusContext', context: 'ci/x', state: 'PENDING' }]))
  })

  it('a 200 with an unreadable body has no digest (so it is ignored, not a false change)', async () => {
    const r = await createCheckProbe({}, async () => ({ status: 200, headers: { get: () => 'e' }, json: async () => { throw new Error('bad json') } }))({ kind: 'check-runs', repo: 'o/r', sha: 'a' })
    expect(r).toEqual({ status: 200, etag: 'e', digest: undefined })
  })
})

describe('digests: the list (GraphQL) and the probe (REST) describe the same checks identically', () => {
  it('order and letter case do not matter; state does', () => {
    expect(checksDigest([run('a', 'IN_PROGRESS'), run('b', 'COMPLETED', 'SUCCESS')])).toBe(checksDigest([run('b', 'completed', 'success'), run('a', 'in_progress')]))
    expect(checksDigest([run('a', 'IN_PROGRESS')])).not.toBe(checksDigest([run('a', 'COMPLETED', 'SUCCESS')]))
  })
  it('a status GitHub only expects (never posted) is left out: REST never lists it', () => {
    expect(statusesDigest([{ __typename: 'StatusContext', context: 'a', state: 'PENDING' }, { __typename: 'StatusContext', context: 'b', state: 'EXPECTED' }]))
      .toBe(statusesDigest([{ __typename: 'StatusContext', context: 'a', state: 'PENDING' }]))
  })
})

describe('pendingCheckHeads: which commits to watch, from the cached PR list', () => {
  it('only PRs with checks still pending, one entry per commit, with what the list showed', () => {
    const prs = [
      pr(1, 'aaa', [run('t', 'IN_PROGRESS')]),
      pr(2, 'aaa', [run('t', 'IN_PROGRESS')]),
      pr(3, 'bbb', [run('t', 'COMPLETED', 'SUCCESS')]),
      pr(4, 'ccc', [run('t', 'COMPLETED', 'FAILURE'), run('u', 'IN_PROGRESS')]),
      pr(5, 'ddd', [])
    ]
    const heads = pendingCheckHeads('o/r', prs)
    expect(heads.map((h) => h.sha)).toEqual(['aaa'])
    expect(heads[0]).toEqual({ repo: 'o/r', sha: 'aaa', checkRuns: checksDigest([run('t', 'IN_PROGRESS')]), statuses: null })
  })
  it('commit statuses pending: the status digest is set, and check runs only if it has any', () => {
    const h = pendingCheckHeads('o/r', [pr(1, 'a', [{ __typename: 'StatusContext', context: 'ci', state: 'PENDING' }])])[0]
    expect(h.checkRuns).toBe(null)
    expect(h.statuses).toBe(statusesDigest([{ __typename: 'StatusContext', context: 'ci', state: 'PENDING' }]))
  })
  it('a light list (no rollup, no sha), nulls, or junk: nothing to watch', () => {
    expect(pendingCheckHeads('o/r', [{ number: 1 }, null, pr(2, null, [run('t', 'IN_PROGRESS')])])).toEqual([])
    expect(pendingCheckHeads('o/r', null)).toEqual([])
    expect(pendingCheckHeads('o/r', 'x')).toEqual([])
  })
  it('the full PR list asks for each head commit (a plain field, no extra cost worth noting)', () => {
    const a = prListArgs('o/r')
    expect(a[a.indexOf('--json') + 1].split(',')).toContain('headRefOid')
  })
})
