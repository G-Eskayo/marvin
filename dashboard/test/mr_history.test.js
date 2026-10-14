import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync, existsSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { appendMerge, readMergeHistory } from '../webhook-server/merge_history.js'
import { mergedPrArgs, buildRows, plainReason, createMrHistory } from '../electron/main/mr_history.js'
import { groupByDay, pageOf } from '../src/lib/mr_history_view.js'

// marvin#419: MR Review's Merged view. Merged PRs from GitHub, who merged them, and every refused Approve.
const PR = (n, repo = 'G-Eskayo/marvin') => `https://github.com/${repo}/pull/${n}`
const tmp = () => mkdtempSync(path.join(tmpdir(), 'mrhist-'))

describe('webhook: appendMerge + readMergeHistory', () => {
  it('records a merge and reads it back', () => {
    const d = tmp()
    const file = path.join(d, 'merge-history.jsonl')
    appendMerge(PR(414), 'you', { file, now: () => new Date('2026-10-13T18:47:50Z') })
    expect(readMergeHistory({ mergeFile: file }).merges).toEqual([{ pr_url: PR(414), t: '2026-10-13T18:47:50.000Z', by: 'you' }])
  })

  it('appendMerge never throws (recording must not break a merge)', () => {
    expect(() => appendMerge(PR(1), 'you', { file: '/dev/null/nope/x.jsonl' })).not.toThrow()
  })

  it('reads refusals from the approve-failed log lines, with the code and message', () => {
    const d = tmp()
    const log = path.join(d, 'dashboard-webhook.log')
    writeFileSync(log, [
      'MR-approval webhook listening on http://localhost:7878/approve',
      `2026-10-13T18:46:35.585Z approve failed: ${PR(400)} MAIN_RED at gate: main itself fails this test, so this PR cannot be judged yet: x.py::t`,
      '[gh-watch] change detected on G-Eskayo/marvin at 2026-10-13T18:47:00Z',
      'garbage approve failed: not-a-url'
    ].join('\n'))
    const { refusals } = readMergeHistory({ webhookLog: log })
    expect(refusals).toEqual([{ pr_url: PR(400), t: '2026-10-13T18:46:35.585Z', code: 'MAIN_RED', message: 'main itself fails this test, so this PR cannot be judged yet: x.py::t' }])
  })

  it('reads every log it is given (the approve-failed lines go to the error log), and the same line twice counts once', () => {
    const d = tmp()
    const err = path.join(d, 'err.log'), out = path.join(d, 'out.log')
    const l = `2026-10-13T18:46:35.585Z approve failed: ${PR(400)} MAIN_RED at gate: main red`
    writeFileSync(err, l + '\n')
    writeFileSync(out, l + '\nnoise\n')
    expect(readMergeHistory({ webhookLog: [err, out] }).refusals.length).toBe(1)
  })

  it('also reads refusals and failures from pipeline-failures.jsonl, deduped against the same approve within 2 minutes', () => {
    const d = tmp()
    const log = path.join(d, 'w.log')
    const fails = path.join(d, 'pipeline-failures.jsonl')
    writeFileSync(log, `2026-10-13T10:00:00.000Z approve failed: ${PR(209)} OUT_OF_ORDER at request: Merge #208 first\n`)
    writeFileSync(fails, [
      JSON.stringify({ t: '2026-10-13T10:00:01.000Z', kind: 'refusal', pr_url: PR(209), sig: 'merge:OUT_OF_ORDER', reason: 'OUT_OF_ORDER: Merge #208 first' }),
      JSON.stringify({ t: '2026-10-13T11:00:00.000Z', kind: 'failure', pr_url: PR(210), sig: 'merge:GATE_TESTS_FAILED', reason: 'GATE_TESTS_FAILED: 2 failing' }),
      JSON.stringify({ t: '2026-10-13T11:00:00.000Z', kind: 'failure', ticket: 5, sig: 'run:x', reason: 'no pr' }),
      '{broken'
    ].join('\n'))
    const { refusals } = readMergeHistory({ webhookLog: log, failuresFile: fails })
    expect(refusals.map((r) => [r.pr_url, r.code])).toEqual([[PR(209), 'OUT_OF_ORDER'], [PR(210), 'GATE_TESTS_FAILED']])
  })

  it('counts past merges recorded in ticket stage logs as yours', () => {
    const d = tmp()
    const stages = path.join(d, 'ticket-stages')
    mkdirSync(stages)
    writeFileSync(path.join(stages, 'g-eskayo__marvin-218.json'), JSON.stringify([
      { stage: 'done', status: 'passed', detail: `merged: ${PR(380)}`, timestamp: '2026-10-11T16:02:00+00:00' },
      { stage: 'done', status: 'passed', detail: 'PR raised: x', timestamp: '2026-10-10T00:00:00+00:00' }
    ]))
    writeFileSync(path.join(stages, 'junk.json'), '{nope')
    expect(readMergeHistory({ stagesDir: stages }).merges).toEqual([{ pr_url: PR(380), t: '2026-10-11T16:02:00+00:00', by: 'you' }])
  })

  it('missing files are an empty history, not a crash', () => {
    expect(readMergeHistory({ mergeFile: '/nope/a', failuresFile: '/nope/b', webhookLog: '/nope/c', stagesDir: '/nope/d' })).toEqual({ merges: [], refusals: [] })
  })
})

describe('mergedPrArgs: incremental merged list', () => {
  it('first read asks for everything; later reads only since the newest known merge', () => {
    expect(mergedPrArgs('G-Eskayo/marvin', null)).toEqual(['pr', 'list', '--repo', 'G-Eskayo/marvin', '--state', 'merged', '--limit', '1000', '--json', 'number,title,url,mergedAt'])
    expect(mergedPrArgs('G-Eskayo/marvin', '2026-10-13T18:47:50Z')).toContain('merged:>=2026-10-12')
  })
})

describe('plainReason', () => {
  it.each([
    ['MAIN_RED', 'main was failing'], ['GATE_TESTS_FAILED', 'tests failed'], ['OUT_OF_ORDER', 'merge another PR first'],
    ['CI_PENDING', 'checks still running'], ['NO_UI_EVIDENCE', 'needed screenshots'], ['SENT_BACK', 'sent back for rework'], ['WHATEVER', 'WHATEVER']
  ])('%s → %s', (code, text) => expect(plainReason(code)).toBe(text))
})

describe('buildRows', () => {
  const merged = [
    { url: PR(414), number: 414, title: 'Fix red main', repo: 'G-Eskayo/marvin', mergedAt: '2026-10-13T18:47:50Z' },
    { url: PR(135, 'G-Eskayo/clarity-captions'), number: 135, title: 'ADR 0024 beta ingest', repo: 'G-Eskayo/clarity-captions', mergedAt: '2026-10-13T17:51:22Z' },
    { url: PR(380), number: 380, title: 'Older', repo: 'G-Eskayo/marvin', mergedAt: '2026-10-12T16:02:00Z' }
  ]
  const history = {
    merges: [{ pr_url: PR(414), t: '2026-10-13T18:47:50Z', by: 'you' }, { pr_url: PR(380), t: '2026-10-12T16:02:00Z', by: 'auto' }],
    refusals: [{ pr_url: PR(400), t: '2026-10-13T18:46:35Z', code: 'MAIN_RED', message: 'm' }, { pr_url: PR(414), t: '2026-10-13T18:40:00Z', code: 'CI_PENDING', message: 'wait' }]
  }
  const rows = buildRows(merged, history, [{ url: PR(400), number: 400, title: 'Implement #218', repo: 'G-Eskayo/marvin' }])

  it('newest first, merges and refusals in one list', () => {
    expect(rows.map((r) => `${r.kind}:${r.number}`)).toEqual(['merged:414', 'refused:400', 'refused:414', 'merged:135', 'merged:380'])
  })
  it('who merged: you, auto, or unrecorded when MARVIN has no record (never guessed)', () => {
    expect(Object.fromEntries(rows.filter((r) => r.kind === 'merged').map((r) => [r.number, r.by]))).toEqual({ 414: 'you', 135: 'unrecorded', 380: 'auto' })
  })
  it('a refused PR carries its title (from the open list) and a plain reason, never a bare number', () => {
    const r = rows.find((x) => x.kind === 'refused' && x.number === 400)
    expect(r).toMatchObject({ title: 'Implement #218', repo: 'G-Eskayo/marvin', reason: 'main was failing' })
  })
  it('a refusal for a PR we know nothing else about still gets a readable title', () => {
    const r = buildRows([], { merges: [], refusals: [{ pr_url: PR(9), t: '2026-10-13T00:00:00Z', code: 'X' }] }, [])[0]
    expect(r.title).toBe('(title unknown)')
    expect(r.number).toBe(9)
  })
  it('refusals with no parsable PR url are dropped', () => {
    expect(buildRows([], { merges: [], refusals: [{ pr_url: 'nope', t: 'x', code: 'X' }] }, [])).toEqual([])
  })
})

describe('createMrHistory: instant from cache, then incremental', () => {
  function setup({ ghList, webhook = async () => ({ merges: [], refusals: [] }) } = {}) {
    const dir = tmp()
    return { cachePath: path.join(dir, 'mr-history.json'), ghList, webhook }
  }
  const row = (n, mergedAt, repo = 'G-Eskayo/marvin') => ({ number: n, title: `PR ${n}`, url: PR(n, repo), mergedAt })

  it('first read fetches everything per repo, then only since the newest merge, never duplicating', async () => {
    const calls = []
    const ghList = vi.fn(async (repo, since) => {
      calls.push([repo, since])
      return since ? [row(2, '2026-10-13T10:00:00Z'), row(3, '2026-10-13T12:00:00Z')] : [row(1, '2026-10-12T09:00:00Z'), row(2, '2026-10-13T10:00:00Z')]
    })
    const s = setup({ ghList })
    const h = createMrHistory({ repos: () => ['G-Eskayo/marvin'], ghList, webhookHistory: s.webhook, openPrs: async () => [], cachePath: s.cachePath, now: () => 1000 })
    await h.get({ fresh: true })
    const second = await h.get({ fresh: true })
    expect(calls).toEqual([['G-Eskayo/marvin', null], ['G-Eskayo/marvin', '2026-10-13T10:00:00Z']])
    expect(second.rows.map((r) => r.number)).toEqual([3, 2, 1])
  })

  it('a non-fresh read answers instantly from the saved cache, with when it was saved', async () => {
    const ghList = vi.fn(async () => [row(1, '2026-10-12T09:00:00Z')])
    const s = setup({ ghList })
    const mk = () => createMrHistory({ repos: () => ['G-Eskayo/marvin'], ghList, webhookHistory: s.webhook, openPrs: async () => [], cachePath: s.cachePath, now: () => 5000 })
    await mk().get({ fresh: true })
    ghList.mockClear()
    const r = await mk().get()
    expect(ghList).not.toHaveBeenCalled()
    expect(r.rows.map((x) => x.number)).toEqual([1])
    expect(r.updatedAt).toBe(5000)
  })

  it('a repo that fails is skipped and named, not an empty history', async () => {
    const ghList = vi.fn(async (repo) => { if (repo.endsWith('bad')) throw new Error('rate limited'); return [row(1, '2026-10-12T09:00:00Z')] })
    const s = setup({ ghList })
    const h = createMrHistory({ repos: () => ['G-Eskayo/marvin', 'G-Eskayo/bad'], ghList, webhookHistory: s.webhook, openPrs: async () => [], cachePath: s.cachePath, now: () => 1 })
    const r = await h.get({ fresh: true })
    expect(r.rows.length).toBe(1)
    expect(r.errors).toEqual([{ repo: 'G-Eskayo/bad', message: 'rate limited' }])
  })

  it('the webhook being unreachable still shows merges (by unknown → GitHub) and says so', async () => {
    const ghList = vi.fn(async () => [row(1, '2026-10-12T09:00:00Z')])
    const s = setup({ ghList })
    const h = createMrHistory({ repos: () => ['G-Eskayo/marvin'], ghList, webhookHistory: async () => { throw new Error('ECONNREFUSED') }, openPrs: async () => [], cachePath: s.cachePath, now: () => 1 })
    const r = await h.get({ fresh: true })
    expect(r.rows[0].by).toBe('unrecorded')
    expect(r.errors[0]).toMatchObject({ repo: 'merge server' })
  })

  it('a corrupt cache is rebuilt, and simultaneous refreshes share one fetch', async () => {
    let n = 0
    const ghList = vi.fn(async () => { n++; await new Promise((r) => setTimeout(r, 20)); return [row(1, '2026-10-12T09:00:00Z')] })
    const s = setup({ ghList })
    writeFileSync(s.cachePath, '{nope')
    const h = createMrHistory({ repos: () => ['G-Eskayo/marvin'], ghList, webhookHistory: s.webhook, openPrs: async () => [], cachePath: s.cachePath, now: () => 1 })
    const [a, b] = await Promise.all([h.get({ fresh: true }), h.get({ fresh: true })])
    expect(n).toBe(1)
    expect(a.rows).toEqual(b.rows)
    expect(JSON.parse(readFileSync(s.cachePath, 'utf-8')).merged.length).toBe(1)
  })

  it('no cache and not fresh: says it has nothing yet instead of hitting GitHub', async () => {
    const ghList = vi.fn()
    const s = setup({ ghList })
    const r = await createMrHistory({ repos: () => ['G-Eskayo/marvin'], ghList, webhookHistory: s.webhook, openPrs: async () => [], cachePath: s.cachePath, now: () => 1 }).get()
    expect(r).toMatchObject({ rows: [], updatedAt: null })
    expect(ghList).not.toHaveBeenCalled()
    expect(existsSync(s.cachePath)).toBe(false)
  })
})

describe('groupByDay + pageOf', () => {
  const NOW = new Date('2026-10-13T20:00:00')
  const at = (d) => new Date(d).toISOString()
  const rows = [
    { kind: 'merged', number: 1, at: at('2026-10-13T12:47:00') },
    { kind: 'refused', number: 2, at: at('2026-10-13T09:00:00') },
    { kind: 'merged', number: 3, at: at('2026-10-12T16:02:00') },
    { kind: 'merged', number: 4, at: at('2026-10-01T10:00:00') }
  ]
  it('Today, Yesterday, then dates, keeping order', () => {
    const days = groupByDay(rows, NOW)
    expect(days.map((d) => d.label)).toEqual(['Today', 'Yesterday', expect.stringMatching(/Oct 1/)])
    expect(days[0].rows.map((r) => r.number)).toEqual([1, 2])
  })
  it('5 days per page, with page count and clamping', () => {
    const many = Array.from({ length: 12 }, (_, i) => ({ kind: 'merged', number: i, at: at(`2026-09-${String(20 - i).padStart(2, '0')}T10:00:00`) }))
    const days = groupByDay(many, NOW)
    expect(pageOf(days, 0)).toMatchObject({ page: 0, pages: 3 })
    expect(pageOf(days, 0).days.length).toBe(5)
    expect(pageOf(days, 2).days.length).toBe(2)
    expect(pageOf(days, 9).page).toBe(2)
    expect(pageOf(days, -1).page).toBe(0)
    expect(pageOf([], 0)).toEqual({ page: 0, pages: 1, days: [] })
  })
  it('rows with unreadable times go last, never crash', () => {
    expect(groupByDay([{ kind: 'merged', number: 9, at: 'nope' }], NOW)[0].label).toBe('Unknown date')
  })
})
