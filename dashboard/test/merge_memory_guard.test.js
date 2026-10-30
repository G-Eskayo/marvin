// marvin#845: the merge gate's rebase + retest is heavy work, so it waits while macOS reports memory pressure at warn
// or critical (lib/memory_guard.py). Refused in plain words, the Approve is queued to run again when pressure drops,
// and nothing running is stopped.
import { describe, it, expect, vi } from 'vitest'

vi.mock('../webhook-server/ticket_stages.js', () => ({ recordStage: vi.fn() }))
vi.mock('../webhook-server/failure_log.js', () => ({ recordFailure: vi.fn() }))
vi.mock('../webhook-server/rebase_status.js', () => ({ writeRebaseStatus: vi.fn(), readRebaseStatus: vi.fn(() => ({})) }))
vi.mock('../webhook-server/ui_evidence.js', () => ({ assertUiEvidence: vi.fn(async () => {}) }))
vi.mock('../webhook-server/decisions_gate.js', () => ({ assertDecisions: vi.fn(async () => {}) }))
vi.mock('../webhook-server/changelog.js', () => ({ applyVersionBump: vi.fn().mockResolvedValue(undefined) }))

import { mergePr, memoryGuardCheck, kickMemoryGuard } from '../webhook-server/merge.js'

const PR = 'https://github.com/G-Eskayo/marvin/pull/851'

function ghExec() {
  return vi.fn(async (cmd, args) => {
    if (cmd === 'gh' && args[0] === 'pr' && args[1] === 'view') {
      const fields = args[args.indexOf('--json') + 1] || ''
      if (fields.includes('statusCheckRollup')) return { stdout: JSON.stringify({ statusCheckRollup: [] }), stderr: '' }
      if (fields.includes('isDraft')) return { stdout: JSON.stringify({ isDraft: false }), stderr: '' }
      if (fields.includes('baseRefName')) return { stdout: 'main\n', stderr: '' }
      return { stdout: JSON.stringify({ labels: [], comments: [], mergeable: 'MERGEABLE', mergeStateStatus: 'CLEAN' }), stderr: '' }
    }
    if (cmd === 'gh' && args[0] === 'api') return { stdout: '[]', stderr: '' }
    return { stdout: '', stderr: '' }
  })
}

const gated = () => vi.fn().mockResolvedValue({ gate: true, headRefName: 'ticket/851-x', body: 'Closes #851' })
const run = (exec, gate, rebase, deps) => mergePr(PR, exec, () => {}, () => {}, gate, rebase, vi.fn(), vi.fn(), deps)

describe('the merge gate under memory pressure', () => {
  it('refuses before the rebase + retest, with the plain message, and never merges', async () => {
    const exec = ghExec()
    const rebase = vi.fn().mockResolvedValue({ ok: true })
    const memoryCheck = vi.fn().mockResolvedValue({ ok: false, queued: true, message: "The Mac mini's memory is under pressure, so PR #851 waits." })
    await expect(run(exec, gated(), rebase, { memoryCheck })).rejects.toMatchObject({
      payload: { code: 'MEMORY_PRESSURE', stage: 'gate', action: 'retry', message: expect.stringContaining('so PR #851 waits') }
    })
    expect(memoryCheck).toHaveBeenCalledWith(PR)
    expect(rebase).not.toHaveBeenCalled()
    expect(exec.mock.calls.some(([c, a]) => c === 'gh' && a[1] === 'merge')).toBe(false)
  })

  it('goes ahead when memory is normal', async () => {
    const rebase = vi.fn().mockResolvedValue({ ok: true })
    await run(ghExec(), gated(), rebase, { memoryCheck: vi.fn().mockResolvedValue({ ok: true }) })
    expect(rebase).toHaveBeenCalled()
  })

  it('a broken check never blocks a merge (same as an unreadable disk)', async () => {
    const rebase = vi.fn().mockResolvedValue({ ok: true })
    await run(ghExec(), gated(), rebase, { memoryCheck: vi.fn().mockRejectedValue(new Error('spawn ENOENT')) })
    expect(rebase).toHaveBeenCalled()
  })

  it('an ungated merge (one GitHub call, no retest) is not held for memory', async () => {
    const memoryCheck = vi.fn()
    const notGated = vi.fn().mockResolvedValue({ gate: false, headRefName: 'ticket/851-x', body: 'Closes #851' })
    await run(ghExec(), notGated, vi.fn(), { memoryCheck })
    expect(memoryCheck).not.toHaveBeenCalled()
  })
})

describe('memoryGuardCheck', () => {
  it('asks memory_guard.py, queueing this same Approve to the local webhook', async () => {
    const exec = vi.fn().mockResolvedValue({ stdout: '{"ok": true}', stderr: '' })
    expect(await memoryGuardCheck(PR, 7878, exec)).toEqual({ ok: true })
    const [py, args] = exec.mock.calls[0]
    expect(py).toMatch(/venv\/bin\/python$/)
    expect(args[0]).toMatch(/lib\/memory_guard\.py$/)
    expect(args.slice(1, 6)).toEqual(['check', '--what', 'PR #851', '--key', `merge:${PR}`])
    const cmd = args.slice(args.indexOf('--') + 1)
    expect(cmd[0]).toBe('/usr/bin/curl')
    expect(cmd.at(-1)).toBe('http://127.0.0.1:7878/approve')
    expect(JSON.parse(cmd[cmd.indexOf('--data') + 1])).toEqual({ pr_url: PR, by: 'you' })
  })

  it('exit 3 is a refusal with the message memory_guard printed', async () => {
    const err = Object.assign(new Error('Command failed'), { code: 3, stderr: "The Mac mini's memory is under pressure, so PR #851 waits.\n", stdout: '{"queued": true}' })
    const r = await memoryGuardCheck(PR, 7878, vi.fn().mockRejectedValue(err))
    expect(r).toEqual({ ok: false, queued: true, message: "The Mac mini's memory is under pressure, so PR #851 waits." })
  })

  it('any other failure lets the merge go ahead', async () => {
    const r = await memoryGuardCheck(PR, 7878, vi.fn().mockRejectedValue(Object.assign(new Error('ENOENT'), { code: 'ENOENT' })))
    expect(r).toEqual({ ok: true })
  })
})

describe('kickMemoryGuard', () => {
  it('starts the next queued item in the background when a merge ends', () => {
    const unref = vi.fn()
    const spawnFn = vi.fn().mockReturnValue({ unref })
    kickMemoryGuard(spawnFn)
    const [py, args, opts] = spawnFn.mock.calls[0]
    expect(py).toMatch(/venv\/bin\/python$/)
    expect(args[0]).toMatch(/lib\/memory_guard\.py$/)
    expect(args.slice(1)).toEqual(['kick'])
    expect(opts).toMatchObject({ detached: true, stdio: 'ignore' })
    expect(unref).toHaveBeenCalled()
  })

  it('never throws', () => {
    expect(() => kickMemoryGuard(() => { throw new Error('EAGAIN') })).not.toThrow()
  })
})
