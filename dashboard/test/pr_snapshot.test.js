import { describe, it, expect, vi } from 'vitest'
import { snapshotExec, SNAPSHOT_FIELDS } from '../webhook-server/pr_snapshot.js'

const URL = 'https://github.com/G-Eskayo/marvin/pull/569'
const PR = { baseRefName: 'main', body: 'Closes #560', isDraft: false, files: [{ path: 'a.js' }], headRefName: 'feat/x', statusCheckRollup: [{ __typename: 'CheckRun', name: 'ci', status: 'COMPLETED', conclusion: 'SUCCESS' }] }

function fakeExec(pr = PR, { fail = false } = {}) {
  return vi.fn(async (cmd, args) => {
    if (cmd === 'gh' && args[0] === 'pr' && args[1] === 'view') {
      if (fail) throw Object.assign(new Error('Command failed'), { stderr: 'HTTP 502' })
      const fields = args[args.indexOf('--json') + 1].split(',')
      return { stdout: JSON.stringify(Object.fromEntries(fields.map((f) => [f, f === 'mergeable' ? 'MERGEABLE' : pr[f]]))) }
    }
    return { stdout: '' }
  })
}
const view = (fields, url = URL) => ['pr', 'view', url, '--json', fields]

// The approve preflight read the same PR one field at a time, 7 times in a row (5.5 s for PR #569, 2026-10-21).
describe('snapshotExec: the approve preflight reads the PR once', () => {
  it('the preflight\'s seven field reads cost one GitHub read, and each gets exactly its fields', async () => {
    const exec = fakeExec()
    const wrapped = snapshotExec(URL, exec)
    const answers = []
    for (const f of ['baseRefName', 'body', 'isDraft', 'files,body', 'body', 'headRefName,body', 'statusCheckRollup']) {
      answers.push(JSON.parse((await wrapped('gh', view(f))).stdout))
    }
    expect(exec).toHaveBeenCalledTimes(1)
    expect(exec.mock.calls[0][1][4].split(',').sort()).toEqual([...SNAPSHOT_FIELDS].sort())
    expect(answers[0]).toEqual({ baseRefName: 'main' })
    expect(answers[3]).toEqual({ files: PR.files, body: PR.body })
    expect(answers[6]).toEqual({ statusCheckRollup: PR.statusCheckRollup })
  })

  it('concurrent first reads share one request', async () => {
    const exec = fakeExec()
    const wrapped = snapshotExec(URL, exec)
    await Promise.all([wrapped('gh', view('body')), wrapped('gh', view('isDraft'))])
    expect(exec).toHaveBeenCalledTimes(1)
  })

  it('mergeable is never served from the snapshot: GitHub recomputes it after every push', async () => {
    const exec = fakeExec()
    const wrapped = snapshotExec(URL, exec)
    await wrapped('gh', view('body'))
    await wrapped('gh', view('mergeable'))
    await wrapped('gh', view('mergeable'))
    expect(exec).toHaveBeenCalledTimes(3)
  })

  it('anything that writes (gh pr ready, a push, the merge) ends the snapshot: later reads go to GitHub', async () => {
    for (const write of [['gh', ['pr', 'ready', URL]], ['git', ['push', 'origin', 'feat/x']], ['gh', ['pr', 'merge', URL, '--merge']], ['gh', ['api', '-X', 'POST', 'x']]]) {
      const exec = fakeExec()
      const wrapped = snapshotExec(URL, exec)
      await wrapped('gh', view('isDraft'))
      await wrapped(...write)
      await wrapped('gh', view('body'))
      expect(exec.mock.calls.filter((c) => c[1][1] === 'view')).toHaveLength(2)
    }
  })

  it('reads that change nothing on GitHub (git fetch, rev-list, issue view) keep the snapshot', async () => {
    const exec = fakeExec()
    const wrapped = snapshotExec(URL, exec)
    await wrapped('gh', view('body'))
    await wrapped('git', ['fetch', 'origin', 'main'])
    await wrapped('git', ['rev-list', '--count', 'a..b'])
    await wrapped('gh', ['issue', 'view', '560', '--repo', 'G-Eskayo/marvin', '--json', 'labels'])
    await wrapped('gh', view('statusCheckRollup'))
    expect(exec.mock.calls.filter((c) => c[1][1] === 'view' && c[1][0] === 'pr')).toHaveLength(1)
  })

  it('another PR, extra flags (--jq), or a field outside the snapshot pass straight through', async () => {
    const exec = fakeExec()
    const wrapped = snapshotExec(URL, exec)
    await wrapped('gh', view('body', 'https://github.com/G-Eskayo/marvin/pull/1'))
    await wrapped('gh', ['pr', 'view', URL, '--json', 'files', '--jq', '.files[].path'])
    await wrapped('gh', view('state'))
    expect(exec).toHaveBeenCalledTimes(3)
    expect(exec.mock.calls.every((c) => !String(c[1][4]).includes('isDraft'))).toBe(true)
  })

  it('the combined read failing falls back to each check\'s own read, so their fail-open rules still apply', async () => {
    const exec = fakeExec(PR, { fail: true })
    const wrapped = snapshotExec(URL, exec)
    await expect(wrapped('gh', view('body'))).rejects.toThrow()
    await expect(wrapped('gh', view('isDraft'))).rejects.toThrow()
    expect(exec).toHaveBeenCalledTimes(3) // one combined try, then each read on its own
  })

  it('a garbled combined answer is not trusted', async () => {
    const exec = vi.fn(async (cmd, args) => (args[4] && args[4].includes(',') && args[4].split(',').length > 3 ? { stdout: 'not json' } : { stdout: JSON.stringify({ body: 'own read' }) }))
    const wrapped = snapshotExec(URL, exec)
    expect(JSON.parse((await wrapped('gh', view('body'))).stdout)).toEqual({ body: 'own read' })
  })

  it('passes options (timeouts, cwd) through untouched', async () => {
    const exec = fakeExec()
    const wrapped = snapshotExec(URL, exec)
    await wrapped('git', ['status'], { cwd: '/x' }, 1234)
    expect(exec).toHaveBeenCalledWith('git', ['status'], { cwd: '/x' }, 1234)
  })

  it('not a PR url: no snapshot at all', async () => {
    const exec = fakeExec()
    expect(snapshotExec('nonsense', exec)).toBe(exec)
  })
})
