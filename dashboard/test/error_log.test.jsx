import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, readFileSync, writeFileSync, existsSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { renderToStaticMarkup } from 'react-dom/server'
import { appendError } from '../electron/main/error_log.js'
import { timed } from '../electron/main/timing.js'
import { createGithubState } from '../electron/main/github_state.js'
import { prFetchBanner } from '../src/lib/pr_fetch_status.js'
import { RecentErrors } from '../src/components/HealthDashboard.jsx'
import { ViewToggle } from '../src/components/MrReview.jsx'

// marvin#422: errors are never silent. The dashboard writes the same errors.jsonl lines lib/error_log.py reads.
const tmp = () => path.join(mkdtempSync(path.join(tmpdir(), 'errlog-')), 'errors.jsonl')
const read = (f) => readFileSync(f, 'utf-8').trim().split('\n').map((l) => JSON.parse(l))

describe('appendError', () => {
  it('writes one line in error_log.py\'s shape, leaving machine for the reader to fill in', () => {
    const f = tmp()
    appendError({ source: 'dashboard:mr:list', message: 'gh failed', raw: 'error connecting to api.github.com' }, { file: f, now: () => new Date('2026-10-14T15:03:49Z') })
    expect(read(f)).toEqual([{ t: '2026-10-14T15:03:49.000Z', machine: null, source: 'dashboard:mr:list', message: 'gh failed', raw: 'error connecting to api.github.com' }])
  })
  it('caps long text and accepts an Error as raw', () => {
    const f = tmp()
    appendError({ source: 's', message: 'm'.repeat(9000), raw: new Error('x'.repeat(20000)) }, { file: f })
    const [e] = read(f)
    expect(e.message.length).toBeLessThanOrEqual(500)
    expect(e.raw.length).toBeLessThanOrEqual(4000)
    expect(e.raw).toMatch(/^Error: x/)
  })
  it('never throws, even when it cannot write', () => {
    expect(() => appendError({ source: 's', message: 'm' }, { file: '/dev/null/nope/errors.jsonl' })).not.toThrow()
  })
  it('stays bounded: past the size limit it keeps only the newest lines', () => {
    const f = tmp()
    writeFileSync(f, Array.from({ length: 3000 }, (_, i) => JSON.stringify({ t: 'x', source: 'old', message: String(i) })).join('\n') + '\n')
    appendError({ source: 'new', message: 'latest' }, { file: f, maxBytes: 10_000, keepLines: 50 })
    const lines = read(f)
    expect(lines.length).toBeLessThanOrEqual(51)
    expect(lines.at(-1).message).toBe('latest')
  })
})

describe('timed() records the failure, not just ok:false', () => {
  it('a throwing IPC handler leaves its message in the error log and still throws', async () => {
    const errors = []
    const fn = timed('ipc', 'mr:historyDetail', async () => { throw new Error('gh: error connecting to api.github.com') }, { record: () => {}, recordError: (e) => errors.push(e) })
    await expect(fn()).rejects.toThrow(/api\.github\.com/)
    expect(errors).toEqual([{ source: 'dashboard:mr:historyDetail', message: 'mr:historyDetail failed', raw: expect.stringMatching(/api\.github\.com/) }])
  })
  it('a broken error recorder never masks the real error', async () => {
    const fn = timed('ipc', 'x', async () => { throw new Error('real') }, { record: () => {}, recordError: () => { throw new Error('recorder broke') } })
    await expect(fn()).rejects.toThrow('real')
  })
})

describe('github_state says which repos it is answering from a stale copy', () => {
  it('a failed refresh serves the old value AND reports the repo, until a refresh succeeds', async () => {
    let t = 0
    const gs = createGithubState({ now: () => t, safetyMs: 10, cooldownUntil: () => 0 })
    await gs.get('prs', 'a/b', async () => [1])
    t = 100
    expect(await gs.get('prs', 'a/b', async () => { throw new Error('error connecting to api.github.com') }, { fresh: true })).toEqual([1])
    expect(gs.failing('prs')).toEqual([{ repo: 'a/b', message: 'error connecting to api.github.com', since: 100 }])
    t = 200
    await gs.get('prs', 'a/b', async () => [2], { fresh: true })
    expect(gs.failing('prs')).toEqual([])
  })
  it('only the asked kind is reported', async () => {
    const gs = createGithubState({ now: () => 0, cooldownUntil: () => 0 })
    await expect(gs.get('issues', 'a/b', async () => { throw new Error('boom') })).rejects.toThrow()
    expect(gs.failing('prs')).toEqual([])
    expect(gs.failing('issues').length).toBe(1)
  })
})

describe('prFetchBanner: never an empty list that looks like "nothing to review"', () => {
  const at = Date.parse('2026-10-14T15:00:00Z')
  it('every project failing says so, with the cause and the age of what is shown', () => {
    const b = prFetchBanner({ errors: Array.from({ length: 13 }, (_, i) => ({ repo: `G-Eskayo/r${i}`, message: 'error connecting to api.github.com' })), projects: 13, lastGoodAt: at - 5 * 60_000 }, at)
    expect(b.tone).toBe('red')
    expect(b.text).toBe("Couldn't reach GitHub for all 13 projects (no network, or GitHub unreachable). Showing the list from 5 min ago.")
  })
  it('some failing names them', () => {
    const b = prFetchBanner({ errors: [{ repo: 'G-Eskayo/nourished', message: 'API rate limit exceeded' }], projects: 13, lastGoodAt: at }, at)
    expect(b.tone).toBe('amber')
    expect(b.text).toContain('nourished')
    expect(b.text).toContain('GitHub rate limit')
  })
  it('nothing failing: no banner', () => {
    expect(prFetchBanner({ errors: [], projects: 13 }, at)).toBeNull()
  })
  it('all failing with nothing ever loaded says there is no list yet', () => {
    const b = prFetchBanner({ errors: [{ repo: 'a/b', message: 'x' }], projects: 1, lastGoodAt: null }, at)
    expect(b.text).toMatch(/No list to show yet/)
  })
})

describe('Health: Recent errors', () => {
  const groups = [
    { machine: 'mac-mini', source: 'sync:pull', cause: 'git is locked by a crashed command', count: 52, first_t: '2026-10-13T18:56:00Z', last_t: '2026-10-14T14:56:00Z', severity: 'red', raw: "fatal: Unable to create '/x/.git/index.lock': File exists." },
    { machine: 'macbook-pro', source: 'dashboard:mr:list', cause: 'no network, or GitHub unreachable', count: 1, first_t: '2026-10-14T15:03:00Z', last_t: '2026-10-14T15:03:00Z', severity: 'amber', raw: 'error connecting' }
  ]
  it('lists each kind of error with machine, source, plain cause and how many times', () => {
    const html = renderToStaticMarkup(<RecentErrors errors={groups} now={Date.parse('2026-10-14T15:05:00Z')} />)
    expect(html).toContain('git is locked by a crashed command')
    expect(html).toContain('mac-mini')
    expect(html).toContain('sync:pull')
    expect(html).toContain('×52')
    expect(html).toContain('data-severity="red"')
  })
  it('none: says so plainly', () => {
    expect(renderToStaticMarkup(<RecentErrors errors={[]} />)).toContain('No errors in the last 24 hours')
  })
  it('missing data (old status file) renders nothing rather than claiming "no errors"', () => {
    expect(renderToStaticMarkup(<RecentErrors errors={undefined} />)).toBe('')
  })
})

describe('the Open count is "?" when the list could not be read', () => {
  it('renders Open (?)', () => {
    expect(renderToStaticMarkup(<ViewToggle view="open" setView={() => {}} openCount="?" />)).toContain('Open (?)')
  })
})
