import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import http from 'http'
import { describeHelper, listHelpers, helperStatus, STALE_MS } from '../webhook-server/chat_helpers.js'
import { createHelpersReader, fetchHelpersFrom, REMOTE_TTL_MS } from '../electron/main/chat_helpers.js'
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
})
