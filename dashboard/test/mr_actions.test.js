import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'fs'
import { createGithubState } from '../electron/main/github_state.js'
import { createLocalFirst, coalesce } from '../electron/main/local_first.js'
import { createMrActions } from '../electron/main/mr_actions.js'
import { listOpenPrsAcrossRepos, prListArgs } from '../electron/main/mr_repos.js'

process.env.MARVIN_GH_GATE_STATE = '/nonexistent/gh-gate.json'

const REPO = 'G-Eskayo/marvin'
const URL = `https://github.com/${REPO}/pull/569`
const BODY = `Closes #560

## Decisions
<!-- marvin:decisions -->
### local-first: Record the rule?
- [ ] Yes
- [ ] No
`
const REPOS = [REPO, ...Array.from({ length: 12 }, (_, i) => `G-Eskayo/p${i}`)] // 13 repos, as on 2026-10-21

// A fake GitHub behind a fake gh: an issue store, PR lists per repo, every call counted by kind. It answers like the
// real one (PATCH --include returns headers and the stored issue).
function fakeGithub({ rejectPatch = false, storeOther = null, offline = false } = {}) {
  const issues = new Map([[569, { number: 569, body: BODY, state: 'open', labels: [], pull_request: {} }], [560, { number: 560, body: 't', state: 'open', labels: [] }]])
  const calls = []
  const exec = vi.fn(async (cmd, args) => {
    calls.push(args.slice(0, 2).join(' '))
    if (offline) throw Object.assign(new Error('Command failed'), { stderr: 'error connecting to api.github.com' })
    if (args[0] === 'pr' && args[1] === 'list') {
      const repo = args[args.indexOf('--repo') + 1]
      const light = args[args.indexOf('--json') + 1] === 'number,title,url'
      const prs = repo === REPO ? [{ number: 569, title: 'P', url: URL, ...(light ? {} : { body: issues.get(569).body, files: [{ path: 'a.js' }], baseRefName: 'main', headRefName: 'f', headRefOid: 'sha1', mergeable: 'MERGEABLE', statusCheckRollup: [] }) }] : []
      return { stdout: JSON.stringify(prs) }
    }
    if (args[0] === 'api' && args[2] === 'PATCH') {
      if (rejectPatch) throw Object.assign(new Error('Command failed'), { stderr: 'HTTP 422: Validation Failed' })
      const sent = JSON.parse(readFileSync(args[args.indexOf('--input') + 1], 'utf8')).body
      const n = Number(args[3].split('/').pop())
      issues.get(n).body = storeOther ? storeOther(sent) : sent
      return { stdout: `HTTP/2.0 200 OK\r\nEtag: W/"e${calls.length}"\r\n\r\n${JSON.stringify(issues.get(n))}` }
    }
    if (args[0] === 'api' && /\/comments$/.test(args[1])) return { stdout: 'https://github.com/x#c\n' }
    if (args[0] === 'api') return { stdout: JSON.stringify(issues.get(Number(args[1].split('/').pop()))) }
    if (args[0] === 'issue' && args[1] === 'list') return { stdout: '[]' }
    return { stdout: '{}' }
  })
  const readIssue = vi.fn(async (repo, n) => {
    calls.push('conditional issue read')
    if (offline) throw new Error('offline')
    return { status: 200, etag: 'W/"z"', issue: issues.get(n) }
  })
  const headCheck = vi.fn(async () => { calls.push('conditional pulls read'); return { fresh: !offline } })
  return { exec, calls, issues, readIssue, headCheck }
}

// The same wiring index.js uses: per-repo memory (github_state), the cross-repo list, mr:list coalesced.
function app(gh, { notify = vi.fn() } = {}) {
  const state = createGithubState({ now: () => 0 })
  const ghList = (light) => async (repo) => JSON.parse((await gh.exec('gh', prListArgs(repo, { light }))).stdout)
  const listOpenPrs = async ({ light = false, fresh = false } = {}) => (await listOpenPrsAcrossRepos(REPOS, (repo) => state.get(light ? 'prs-light' : 'prs', repo, () => ghList(light)(repo), { fresh }))).prs
  const mrList = coalesce(() => listOpenPrs(), () => state.localSeq())
  const localFirst = createLocalFirst({ state, readIssue: gh.readIssue, onCorrected: (c) => notify('mr:corrected', c) })
  const card = async (url) => (await mrList()).find((p) => p.url === url) || null
  const actions = createMrActions({ state, exec: gh.exec, localFirst, listOpenPrs, card, headCheck: gh.headCheck, notify })
  return { state, listOpenPrs, mrList, actions, notify, localFirst }
}
const settle = () => new Promise((r) => setTimeout(r, 0))

describe('Decisions: answered on GitHub, shown at once, confirmed in the background', () => {
  it('the answer is in the PR the screen gets back, and no repo is re-listed', async () => {
    const gh = fakeGithub()
    const a = app(gh)
    await a.mrList()
    const before = gh.calls.filter((c) => c === 'pr list').length
    const r = await a.actions.submitDecisions({ repo: REPO, number: 569, answers: { 'local-first': { choices: ['Yes'] } } })
    expect(r.pending).toEqual([])
    expect(r.pr.body).toContain('- [x] Yes')
    expect(r.recorded).toBeUndefined() // promises cannot cross IPC
    await settle()
    expect(gh.calls.filter((c) => c === 'pr list').length).toBe(before)
    expect((await a.mrList())[0].body).toContain('- [x] Yes')
  })

  it('GitHub rejects the write: an error, the screen keeps the old state, nothing is recorded', async () => {
    const gh = fakeGithub({ rejectPatch: true })
    const a = app(gh)
    await a.mrList()
    await expect(a.actions.submitDecisions({ repo: REPO, number: 569, answers: { 'local-first': { choices: ['Yes'] } } })).rejects.toThrow()
    expect((await a.mrList())[0].body).toBe(BODY)
    expect(gh.calls.some((c) => c.includes('comments'))).toBe(false)
  })

  it('GitHub stores something else than what was written: the screen shows GitHub\'s and Gil is told', async () => {
    const gh = fakeGithub({ storeOther: () => BODY })
    const notify = vi.fn()
    const a = app(gh, { notify })
    await a.mrList()
    const r = await a.actions.submitDecisions({ repo: REPO, number: 569, answers: { 'local-first': { choices: ['Yes'] } } })
    expect(r.pending).toEqual(['local-first'])
    expect(r.pr.body).toBe(BODY)
    const told = notify.mock.calls.filter(([ch]) => ch === 'mr:corrected')
    expect(told).toHaveLength(1)
    expect(told[0][1].message).toMatch(/Record the rule\?/)
  })

  it('GitHub changes after the write (someone else edited it): the background confirm corrects the view', async () => {
    const gh = fakeGithub()
    const notify = vi.fn()
    const a = app(gh, { notify })
    await a.mrList()
    gh.readIssue.mockImplementationOnce(async () => ({ status: 200, issue: { body: BODY.replace('- [ ] No', '- [x] No'), state: 'open', labels: [] } }))
    await a.actions.submitDecisions({ repo: REPO, number: 569, answers: { 'local-first': { choices: ['Yes'] } } })
    await settle()
    expect((await a.mrList())[0].body).toContain('- [x] No')
    expect(notify.mock.calls.some(([ch, c]) => ch === 'mr:corrected' && /"No"/.test(c.message))).toBe(true)
  })

  it('two rapid submits: both land in order, and the second sees the first', async () => {
    const gh = fakeGithub()
    const a = app(gh)
    await a.mrList()
    const one = a.actions.submitDecisions({ repo: REPO, number: 569, answers: { 'local-first': { choices: ['Yes'] } } })
    const two = a.actions.submitDecisions({ repo: REPO, number: 569, answers: { 'local-first': { choices: ['No'] } } })
    await Promise.all([one, two])
    await settle()
    expect(gh.issues.get(569).body).toContain('- [x] No')
    expect(gh.issues.get(569).body).not.toContain('- [x] Yes')
    expect((await a.mrList())[0].body).toBe(gh.issues.get(569).body)
  })

  it('the record comment arrives later as its own message', async () => {
    const gh = fakeGithub()
    const notify = vi.fn()
    const a = app(gh, { notify })
    await a.actions.submitDecisions({ repo: REPO, number: 569, answers: { 'local-first': { choices: ['Yes'] } } })
    await settle()
    expect(notify).toHaveBeenCalledWith('decisions:recorded', expect.objectContaining({ repo: REPO, number: 569, commentUrl: 'https://github.com/x#c' }))
  })

  it('offline: the submit fails plainly and the screen is unchanged', async () => {
    const gh = fakeGithub()
    const a = app(gh)
    await a.mrList()
    gh.exec.mockImplementation(async () => { throw Object.assign(new Error('Command failed'), { stderr: 'error connecting to api.github.com' }) })
    await expect(a.actions.submitDecisions({ repo: REPO, number: 569, answers: { 'local-first': { choices: ['Yes'] } } })).rejects.toThrow()
    expect((await a.mrList())[0].body).toBe(BODY)
  })
})

describe('Approve: the preflight uses what the dashboard already has, plus one conditional check', () => {
  it('fresh: no PR list is read at all for the order check', async () => {
    const gh = fakeGithub()
    const a = app(gh)
    await a.mrList()
    const before = gh.calls.length
    const prs = await a.actions.approvePrs(URL)
    expect(prs.map((p) => p.number)).toEqual([569])
    expect(gh.calls.slice(before)).toEqual(['conditional pulls read'])
  })

  it('stale (a push, a new PR, offline): re-reads that one repo only, never all 13', async () => {
    const gh = fakeGithub()
    const a = app(gh)
    await a.mrList()
    gh.headCheck.mockResolvedValueOnce({ fresh: false })
    const before = gh.calls.length
    await a.actions.approvePrs(URL)
    expect(gh.calls.slice(before).filter((c) => c === 'pr list')).toHaveLength(1)
  })

  it('merged: the PR leaves the list at once; GitHub confirms it closed', async () => {
    const gh = fakeGithub()
    const notify = vi.fn()
    const a = app(gh, { notify })
    await a.mrList()
    gh.issues.get(569).state = 'closed'
    a.actions.merged(URL)
    expect(await a.mrList()).toEqual([])
    await settle()
    expect(notify).not.toHaveBeenCalledWith('mr:corrected', expect.anything())
  })

  it('merged here but GitHub still shows it open: it comes back, and Gil is told', async () => {
    const gh = fakeGithub()
    const notify = vi.fn()
    const a = app(gh, { notify })
    await a.mrList()
    a.actions.merged(URL)
    await settle()
    expect(notify).toHaveBeenCalledWith('mr:corrected', expect.objectContaining({ message: expect.stringMatching(/still shows #569 open/) }))
    expect((await a.mrList()).map((p) => p.number)).toEqual([569])
  })
})

describe('Deny, send back and clear: the card changes at once', () => {
  async function withTicket(gh) {
    const a = app(gh)
    await a.mrList()
    await a.state.get('board', REPO, async () => ({ issues: [{ number: 560, state: 'OPEN', labels: [] }], prs: [], holdComments: {} }))
    return a
  }
  const labelsOf = async (a) => (await a.state.get('board', REPO, async () => { throw new Error('memory') })).issues[0].labels.map((l) => l.name)

  it('send feedback marks the ticket sent back at once and confirms it', async () => {
    const gh = fakeGithub()
    gh.issues.get(560).labels = [{ name: 'needs-reengagement' }]
    const a = await withTicket(gh)
    a.actions.denied({ url: URL, ticketNumber: 560, action: 'feedback' })
    expect(await labelsOf(a)).toContain('needs-reengagement')
    await settle()
    expect(gh.readIssue).toHaveBeenCalledWith(REPO, 560, undefined)
  })

  it('drop removes the PR at once', async () => {
    const gh = fakeGithub()
    gh.issues.get(569).state = 'closed'
    const a = await withTicket(gh)
    a.actions.denied({ url: URL, ticketNumber: 560, action: 'drop' })
    expect(await a.mrList()).toEqual([])
  })

  it('clearing sent-back removes the label at once; GitHub still having it brings it back with a message', async () => {
    const gh = fakeGithub()
    gh.issues.get(560).labels = [{ name: 'needs-reengagement' }]
    const notify = vi.fn()
    const a = app(gh, { notify })
    await a.state.get('board', REPO, async () => ({ issues: [{ number: 560, state: 'OPEN', labels: [{ name: 'needs-reengagement' }] }], prs: [], holdComments: {} }))
    a.actions.cleared({ url: URL, ticket: 560 })
    expect(await labelsOf(a)).toEqual([])
    await settle()
    expect(await labelsOf(a)).toEqual(['needs-reengagement'])
    expect(notify).toHaveBeenCalledWith('mr:corrected', expect.objectContaining({ message: expect.stringMatching(/still shows ticket #560 as sent back/) }))
  })

  it('a bad url or ticket is ignored, never thrown into the action\'s answer', () => {
    const a = app(fakeGithub())
    expect(() => a.actions.denied({ url: 'nonsense', ticketNumber: 'x', action: 'feedback' })).not.toThrow()
    expect(() => a.actions.merged('nonsense')).not.toThrow()
    expect(() => a.actions.cleared({ url: URL, ticket: null })).not.toThrow()
  })
})

// The call storm (2026-10-21): the cost of a boot and a session of clicks, counted in gh calls. One list per repo at
// boot, then nothing from GitHub until something changes; an action costs its own writes plus O(1) reads.
describe('GitHub call budget: a boot plus a session of clicks', () => {
  it('boot: one full and one light list per repo; repeat screens cost nothing', async () => {
    const gh = fakeGithub()
    const a = app(gh)
    await Promise.all([a.mrList(), a.mrList(), a.mrList(), a.listOpenPrs({ light: true }), a.listOpenPrs({ light: true })])
    for (let i = 0; i < 20; i++) { await a.mrList(); await a.listOpenPrs({ light: true }) } // tab switches, status dot
    expect(gh.calls.filter((c) => c === 'pr list')).toHaveLength(REPOS.length * 2)
  })

  it('answering Decisions and approving costs a handful of calls, and never a re-list', async () => {
    const gh = fakeGithub()
    const a = app(gh)
    await a.mrList()
    await a.listOpenPrs({ light: true })
    const before = gh.calls.length
    await a.actions.submitDecisions({ repo: REPO, number: 569, answers: { 'local-first': { choices: ['Yes'] } } })
    for (let i = 0; i < 5; i++) await a.mrList()
    await a.actions.approvePrs(URL)
    gh.issues.get(569).state = 'closed' // what the merge did on GitHub
    a.actions.merged(URL)
    for (let i = 0; i < 5; i++) { await a.mrList(); await a.listOpenPrs({ light: true }) }
    await settle()
    const used = gh.calls.slice(before)
    expect(used.filter((c) => c === 'pr list')).toHaveLength(0)
    // GET + PATCH + comment, a conditional confirm each for the answer and the merge, one conditional pulls check
    expect(used.length).toBeLessThanOrEqual(6)
  })

  it('offline: a failing GitHub is asked once per repo, then backs off (no storm)', async () => {
    const gh = fakeGithub({ offline: true })
    const a = app(gh)
    for (let i = 0; i < 30; i++) { await a.mrList().catch(() => {}); await a.listOpenPrs({ light: true }).catch(() => {}) }
    expect(gh.calls.filter((c) => c === 'pr list')).toHaveLength(REPOS.length * 2)
  })
})
