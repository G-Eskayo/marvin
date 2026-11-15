import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import http from 'http'
import { describeHelper, listHelpers, helperStatus, STALE_MS } from '../webhook-server/chat_helpers.js'
import { createHelpersReader, fetchHelpersFrom, REMOTE_TTL_MS, filterForHome } from '../electron/main/chat_helpers.js'
import { listJobs } from '../electron/main/jobs.js'
import { ChatHelpersView } from '../src/components/ChatHelpers.jsx'

const T0 = Date.parse('2026-10-22T15:00:00Z')
const iso = (ms) => new Date(ms).toISOString()

// What lib/chat_helpers.py writes (lib/tests/test_chat_helpers.py pins the writer's side).
function helperDoc(id, { status = 'running', started = T0, finished = null, summary = '', error = '', links = [], transcript = '' } = {}) {
  return {
    job: `helper-${id}`,
    label: `Helper ${id}`,
    kind: 'helper',
    helper: { agent_id: id, agent_type: 'general-purpose', session: 'b41ed591', chat: 'fix the docs search', machine: 'macbook-pro', cwd: '/Users/gil', transcript, links },
    runs: [{ id: 'r1', status, started_at: iso(started), finished_at: finished ? iso(finished) : null, steps: [{ step: 'working', detail: '', at: iso(started) }], summary, error }]
  }
}

describe('helperStatus: a helper is never "running" forever', () => {
  it('done and failed come from the stop event', () => {
    expect(helperStatus({ status: 'passed', started_at: iso(T0) }, null, T0)).toBe('done')
    expect(helperStatus({ status: 'failed', started_at: iso(T0) }, null, T0)).toBe('failed')
    expect(helperStatus({ status: 'nonsense', started_at: iso(T0) }, null, T0)).toBe('failed')
  })
  it('a running helper whose transcript went quiet (killed, no stop event) is crashed after the bound', () => {
    const run = { status: 'running', started_at: iso(T0) }
    expect(helperStatus(run, T0 + 60_000, T0 + 60_000 + STALE_MS - 1)).toBe('running')
    expect(helperStatus(run, T0 + 60_000, T0 + 60_000 + STALE_MS + 1)).toBe('crashed')
    expect(helperStatus(run, null, T0 + STALE_MS + 1)).toBe('crashed') // no transcript: measured from the start
    expect(helperStatus({ status: 'running', started_at: 'garbage' }, null, T0)).toBe('crashed')
  })
})

describe('describeHelper', () => {
  it('a finished helper carries its duration, one-line result, chat, machine and links', () => {
    const h = describeHelper(helperDoc('a1', { status: 'passed', finished: T0 + 7 * 60_000, summary: 'Filed #612', links: [{ kind: 'ticket', repo: 'G-Eskayo/marvin', number: 612 }] }), { now: T0 + 8 * 60_000 })
    expect(h).toMatchObject({ id: 'helper-a1', label: 'Helper a1', kind: 'helper', status: 'done', machine: 'macbook-pro' })
    expect(h.schedule).toBe('from “fix the docs search” on macbook-pro')
    expect(h.job.last).toMatchObject({ status: 'passed', durationS: 420, summary: 'Filed #612' })
    expect(h.job.current).toBeNull()
    expect(h.links).toEqual([{ kind: 'ticket', repo: 'G-Eskayo/marvin', number: 612 }])
  })
  it('a killed helper says so instead of showing as running', () => {
    const h = describeHelper(helperDoc('a1'), { now: T0 + STALE_MS + 1000 })
    expect(h.status).toBe('crashed')
    expect(h.job.current).toBeNull()
    expect(h.job.last.error).toMatch(/15 min/)
    const quiet = describeHelper(helperDoc('b', { transcript: '/t' }), { now: T0 + 40 * 60_000, mtime: () => T0 + 20 * 60_000 })
    expect(quiet.job.last).toMatchObject({ durationS: 1200, finishedAt: iso(T0 + 20 * 60_000) }) // ran until it went quiet
  })
  it('drops malformed docs and hostile links', () => {
    expect(describeHelper(null)).toBeNull()
    expect(describeHelper({ job: 'helper-x', runs: [] })).toBeNull()
    expect(describeHelper({ job: 'helper-x', runs: [{ status: 'running' }], helper: {} })).toBeNull()
    expect(describeHelper({ job: 'helper-x', runs: [{ status: 'running', started_at: iso(T0) }] })).toBeNull()
    const bad = [{ kind: 'ticket', repo: 'javascript:alert(1)', number: 1 }, { kind: 'x', repo: 'a/b', number: 1 }, { kind: 'pr', repo: 'a/b', number: '1' }, null, { kind: 'pr', repo: 'a/b', number: 2 }]
    expect(describeHelper(helperDoc('a', { links: bad }), { now: T0 }).links).toEqual([{ kind: 'pr', repo: 'a/b', number: 2 }])
    const odd = describeHelper(helperDoc('a', { status: 'failed', finished: T0, summary: { x: 1 }, error: ['y'] }), { now: T0 })
    expect(odd.job.last).toMatchObject({ summary: '', error: '' }) // never "[object Object]" on screen
  })
})

describe('listHelpers and the jobs list', () => {
  let dir
  beforeEach(() => { dir = mkdtempSync(path.join(tmpdir(), 'helpers-')) })
  afterEach(() => rmSync(dir, { recursive: true, force: true }))

  it('reads only helper logs, skips corrupt ones, and puts running first then newest', () => {
    writeFileSync(path.join(dir, 'helper-a.json'), JSON.stringify(helperDoc('a', { status: 'passed', started: T0, finished: T0 + 1000, summary: 'ok' })))
    writeFileSync(path.join(dir, 'helper-b.json'), JSON.stringify(helperDoc('b', { started: T0 + 5000 })))
    writeFileSync(path.join(dir, 'helper-c.json'), JSON.stringify(helperDoc('c', { status: 'passed', started: T0 + 2000, finished: T0 + 3000, summary: 'ok' })))
    writeFileSync(path.join(dir, 'helper-bad.json'), '{half')
    writeFileSync(path.join(dir, 'tidy-agent.json'), JSON.stringify({ job: 'tidy-agent', runs: [] }))
    expect(listHelpers({ dir, now: T0 + 6000 }).map((h) => h.id)).toEqual(['helper-b', 'helper-c', 'helper-a'])
  })
  it('a transcript still being written keeps a long helper running', () => {
    const transcript = path.join(dir, 'agent-a.jsonl')
    writeFileSync(transcript, '{}\n') // written "now", hours after the start
    writeFileSync(path.join(dir, 'helper-a.json'), JSON.stringify(helperDoc('a', { started: Date.now() - 3 * 3600_000, transcript })))
    expect(listHelpers({ dir })[0].status).toBe('running')
  })
  it('a missing folder is an empty list', () => expect(listHelpers({ dir: path.join(dir, 'nope') })).toEqual([]))
  it('helpers are not counted as this machine\'s agents (Health) or its jobs', () => {
    writeFileSync(path.join(dir, 'helper-a.json'), JSON.stringify(helperDoc('a')))
    writeFileSync(path.join(dir, 'tidy-agent.json'), JSON.stringify({ job: 'tidy-agent', runs: [{ status: 'passed', started_at: iso(T0), finished_at: iso(T0) }] }))
    expect(listJobs({ dir, now: T0 }).map((j) => j.job)).toEqual(['tidy-agent'])
  })
})

describe('the other Mac', () => {
  const local = () => [describeHelper(helperDoc('mine'), { now: T0 })]

  it('merges the other Mac\'s helpers, caches the read, and names a Mac it could not reach', async () => {
    let t = T0
    const calls = []
    const fetchRemote = async (host) => {
      calls.push(host)
      if (host === 'down') return null
      return [{ ...describeHelper(helperDoc('theirs', { status: 'passed', finished: T0 + 1000, summary: 'ok' }), { now: T0 }), machine: '' }]
    }
    const read = createHelpersReader({ listLocal: local, peers: () => [{ id: 'mac-mini-1', host: 'mini' }, { id: 'kali', host: 'down' }], fetchRemote, clock: () => t })
    const r = await read()
    expect(r.helpers.map((h) => h.id)).toEqual(['helper-mine', 'helper-theirs'])
    expect(r.helpers[1].machine).toBe('mac-mini-1') // filled in from which Mac answered
    expect(r.unreachable).toEqual(['kali'])
    await read()
    expect(calls).toEqual(['mini', 'down'])
    t += REMOTE_TTL_MS + 1
    await read()
    expect(calls).toEqual(['mini', 'down', 'mini', 'down'])
  })
  it('drops anything the other Mac sends that is not a helper row', async () => {
    const junk = [null, 5, 'x', { id: 'h', status: 'evil' }, { id: 7, status: 'done' }, { id: 'ok', status: 'done', label: 'L', job: {} }]
    const read = createHelpersReader({ listLocal: () => [], peers: () => [{ id: 'm', host: 'h' }], fetchRemote: async () => junk })
    expect((await read()).helpers.map((h) => h.id)).toEqual(['ok'])
  })

  describe('fetchHelpersFrom (a real local server)', () => {
    let server
    let port
    let reply
    beforeEach(async () => {
      server = http.createServer((req, res) => reply(req, res))
      await new Promise((r) => server.listen(0, '127.0.0.1', r))
      port = server.address().port
    })
    afterEach(() => new Promise((r) => server.close(r)))

    it('reads GET /helpers', async () => {
      reply = (req, res) => res.end(JSON.stringify({ helpers: req.url === '/helpers' ? [{ id: 'x' }] : [] }))
      expect(await fetchHelpersFrom('127.0.0.1', { port })).toEqual([{ id: 'x' }])
    })
    it('a bad status, bad JSON, a wrong shape or a flood is "unreachable", never a crash', async () => {
      reply = (_q, res) => { res.statusCode = 500; res.end('{}') }
      expect(await fetchHelpersFrom('127.0.0.1', { port })).toBeNull()
      reply = (_q, res) => res.end('{nope')
      expect(await fetchHelpersFrom('127.0.0.1', { port })).toBeNull()
      reply = (_q, res) => res.end('{"helpers": "x"}')
      expect(await fetchHelpersFrom('127.0.0.1', { port })).toBeNull()
      reply = (_q, res) => res.end(JSON.stringify({ helpers: ['x'.repeat(600 * 1024)] }))
      expect(await fetchHelpersFrom('127.0.0.1', { port })).toBeNull()
    })
    it('a Mac that never answers times out fast', async () => {
      reply = () => {} // hangs
      const t = Date.now()
      expect(await fetchHelpersFrom('127.0.0.1', { port, timeoutMs: 200 })).toBeNull()
      expect(Date.now() - t).toBeLessThan(2000)
    })
  })
})

describe('Activity rows (rendered from a fixture)', () => {
  const now = T0 + 8 * 60_000
  const data = {
    helpers: [
      describeHelper(helperDoc('run', { started: T0 + 5 * 60_000 }), { now }),
      describeHelper(helperDoc('done', { status: 'passed', finished: T0 + 7 * 60_000, summary: 'Filed G-Eskayo/marvin#612 and opened PR #613', links: [{ kind: 'ticket', repo: 'G-Eskayo/marvin', number: 612 }, { kind: 'pr', repo: 'G-Eskayo/marvin', number: 613 }] }), { now }),
      describeHelper(helperDoc('fail', { status: 'failed', finished: T0 + 60_000, error: 'ended without a result' }), { now })
    ],
    unreachable: ['mac-mini-1']
  }

  it('each helper is a row with what, where from, which Mac, state, duration and result', () => {
    const html = renderToStaticMarkup(<ChatHelpersView data={data} now={now} />)
    expect(html).toContain('data-testid="chat-helpers"')
    expect(html).toContain('Helper run')
    expect(html).toContain('Running')
    expect(html).toContain('3m 0s so far')
    expect(html).toContain('Done')
    expect(html).toContain('took 7m 0s')
    expect(html).toContain('Filed G-Eskayo/marvin#612 and opened PR #613')
    expect(html).toContain('Last run failed')
    expect(html).toContain('ended without a result')
    expect(html).toContain('chat helper · from “fix the docs search” on macbook-pro')
    expect(html).toContain('Not reachable: mac-mini-1.')
  })
  it('the tickets and PRs it names are chips', () => {
    const html = renderToStaticMarkup(<ChatHelpersView data={data} now={now} />)
    expect(html).toContain('title="Open ticket #612">marvin#612</button>')
    expect(html).toContain('title="Open PR #613">PR marvin#613</button>')
  })
  it('nothing to show is nothing at all, not an empty section', () => {
    expect(renderToStaticMarkup(<ChatHelpersView data={null} now={now} />)).toBe('')
    expect(renderToStaticMarkup(<ChatHelpersView data={{ helpers: [] }} now={now} />)).toBe('')
  })

  it('a crashed helper shows a dismiss button when onDismiss is provided', () => {
    const crashedNow = T0 + STALE_MS + 1000 // old enough to be considered crashed
    const helpers = [
      describeHelper(helperDoc('crash'), { now: crashedNow }) // running but quiet long enough to be crashed
    ]
    const data = { helpers, unreachable: [] }
    const onDismiss = vi.fn()
    const html = renderToStaticMarkup(<ChatHelpersView data={data} now={crashedNow} onDismiss={onDismiss} />)
    expect(html).toContain('>Dismiss</button>')
  })

  it('does not show a dismiss button when onDismiss is not provided', () => {
    const crashedNow = T0 + STALE_MS + 1000
    const helpers = [
      describeHelper(helperDoc('crash'), { now: crashedNow })
    ]
    const data = { helpers, unreachable: [] }
    const html = renderToStaticMarkup(<ChatHelpersView data={data} now={crashedNow} />)
    expect(html).not.toContain('>Dismiss</button>')
  })

  it('does not show a dismiss button for running or done helpers', () => {
    const helpers = [
      describeHelper(helperDoc('run', { started: T0 + 5 * 60_000 }), { now }),
      describeHelper(helperDoc('done', { status: 'passed', finished: T0 + 7 * 60_000, summary: 'ok' }), { now })
    ]
    const data = { helpers, unreachable: [] }
    const onDismiss = vi.fn()
    const html = renderToStaticMarkup(<ChatHelpersView data={data} now={now} onDismiss={onDismiss} />)
    expect(html.match(/>Dismiss</g)).toBeNull()
  })

  it('does not nest buttons inside buttons when showing dismiss', () => {
    const crashedNow = T0 + STALE_MS + 1000
    const helpers = [
      describeHelper(helperDoc('crash'), { now: crashedNow })
    ]
    const data = { helpers, unreachable: [] }
    const onDismiss = vi.fn()
    const html = renderToStaticMarkup(<ChatHelpersView data={data} now={crashedNow} onDismiss={onDismiss} />)
    // Verify buttons are siblings: check that dismiss button closes before the history button appears
    expect(html).toMatch(/<\/button>\s*<button[^>]*>Dismiss<\/button>/)
  })
})

describe('filterForHome', () => {
  const makeHelper = (id, { status = 'running', finishedAt = null, startedAt = iso(T0) } = {}) => ({
    id,
    machine: 'test-mac',
    status,
    kind: 'helper',
    job: {
      current: status === 'running' ? { startedAt } : null,
      last: status !== 'running' ? { finishedAt: finishedAt || iso(T0), startedAt, durationS: 60, summary: '' } : null
    }
  })

  it('drops dismissed helpers', () => {
    const helpers = [
      makeHelper('h1', { status: 'done', finishedAt: iso(T0) }),
      makeHelper('h2', { status: 'done', finishedAt: iso(T0) })
    ]
    const dismissed = new Map([['test-mac:h1', Date.now()]])
    const result = filterForHome(helpers, { dismissed, now: T0 })
    expect(result.map((h) => h.id)).toEqual(['h2'])
  })

  it('drops crashed helpers older than maxAgeMs', () => {
    const now = T0 + 25 * 60 * 60 * 1000 // 25 hours later
    const helpers = [
      makeHelper('old', { status: 'crashed', finishedAt: iso(T0) }),
      makeHelper('new', { status: 'crashed', finishedAt: iso(now - 1 * 60 * 60 * 1000) }) // 1 hour ago
    ]
    const result = filterForHome(helpers, { dismissed: new Map(), now, maxAgeMs: 24 * 60 * 60 * 1000 })
    expect(result.map((h) => h.id)).toEqual(['new'])
  })

  it('handles malformed timestamps gracefully', () => {
    const helpers = [
      makeHelper('h1', { status: 'crashed', finishedAt: 'garbage' }),
      makeHelper('h2', { status: 'crashed', finishedAt: iso(Date.now() - 1000) })
    ]
    const result = filterForHome(helpers, { dismissed: new Map(), now: Date.now(), maxAgeMs: 24 * 60 * 60 * 1000 })
    expect(result.map((h) => h.id)).toEqual(['h2'])
  })

  it('never caps running helpers', () => {
    const helpers = Array.from({ length: 15 }, (_, i) => makeHelper(`h${i}`, { status: 'running' }))
    const result = filterForHome(helpers, { dismissed: new Map(), now: Date.now(), cap: 10 })
    expect(result).toHaveLength(15)
  })

  it('caps non-running helpers to the remainder after running helpers are kept', () => {
    const helpers = [
      makeHelper('r1', { status: 'running' }),
      makeHelper('r2', { status: 'running' }),
      makeHelper('d1', { status: 'done', finishedAt: iso(T0) }),
      makeHelper('d2', { status: 'done', finishedAt: iso(T0) }),
      makeHelper('d3', { status: 'done', finishedAt: iso(T0) }),
      makeHelper('d4', { status: 'done', finishedAt: iso(T0) }),
      makeHelper('d5', { status: 'done', finishedAt: iso(T0) })
    ]
    const result = filterForHome(helpers, { dismissed: new Map(), now: T0, cap: 5 })
    expect(result).toHaveLength(5)
    expect(result.slice(0, 2).map((h) => h.id)).toEqual(['r1', 'r2'])
    expect(result.slice(2).map((h) => h.id)).toEqual(['d1', 'd2', 'd3'])
  })

  it('when running helpers outnumber cap, all running helpers are kept and no others are included', () => {
    const helpers = [
      makeHelper('r1', { status: 'running' }),
      makeHelper('r2', { status: 'running' }),
      makeHelper('r3', { status: 'running' }),
      makeHelper('r4', { status: 'running' }),
      makeHelper('r5', { status: 'running' }),
      makeHelper('r6', { status: 'running' }),
      makeHelper('r7', { status: 'running' }),
      makeHelper('r8', { status: 'running' }),
      makeHelper('r9', { status: 'running' }),
      makeHelper('r10', { status: 'running' }),
      makeHelper('r11', { status: 'running' }),
      makeHelper('r12', { status: 'running' }),
      makeHelper('d1', { status: 'done', finishedAt: iso(T0) }),
      makeHelper('d2', { status: 'done', finishedAt: iso(T0) }),
      makeHelper('d3', { status: 'done', finishedAt: iso(T0) })
    ]
    const result = filterForHome(helpers, { dismissed: new Map(), now: T0, cap: 10 })
    expect(result).toHaveLength(12)
    expect(result.every((h) => h.status === 'running')).toBe(true)
  })

  it("uses the most recent run's age, not a previous run's", () => {
    // A helper that crashed but had an older run over 24h ago should not be hidden
    // if the crash happened within the window. This tests that we check job.current
    // before job.last (which might be from an older run in a multi-run helper).
    const now = T0 + 25 * 60 * 60 * 1000 // 25 hours later
    const helpers = [
      {
        id: 'h1',
        machine: 'test-mac',
        status: 'crashed',
        kind: 'helper',
        job: {
          current: null,
          last: {
            finishedAt: iso(now - 10 * 60 * 1000) // crashed 10 minutes ago
          }
        }
      },
      {
        id: 'h2',
        machine: 'test-mac',
        status: 'running',
        kind: 'helper',
        job: {
          current: { startedAt: iso(now - 2 * 60 * 1000) }, // started 2 minutes ago
          last: {
            finishedAt: iso(T0) // previous run finished over 24h ago
          }
        }
      }
    ]
    const result = filterForHome(helpers, { dismissed: new Map(), now, maxAgeMs: 24 * 60 * 60 * 1000 })
    // Both should be kept: h1 crashed recently, h2 is currently running
    expect(result.map((h) => h.id)).toEqual(['h2', 'h1'])
  })
})
