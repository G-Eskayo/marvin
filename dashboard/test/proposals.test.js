import { describe, it, expect } from 'vitest'
import { proposalArgs, createProposals } from '../electron/main/proposals.js'

const runner = (stdout, { err = null, stderr = '' } = {}) => {
  const calls = []
  const run = (cmd, args, opts, cb) => { calls.push(args); cb(err, stdout, stderr) }
  return { run, calls }
}

describe('proposals CLI bridge', () => {
  it('builds list and act arguments, with args as one JSON value', () => {
    expect(proposalArgs('list').slice(1)).toEqual(['list'])
    expect(proposalArgs('act', 'my-idea', 'snooze', { days: 7 }).slice(1)).toEqual(['act', 'my-idea', 'snooze', '--json', '{"days":7}'])
  })

  it('refuses bad ids and unknown actions before running anything', async () => {
    for (const [id, action] of [['../x', 'dismiss'], ['', 'dismiss'], ['--json', 'dismiss'], ['ok-id', 'delete'], ['ok-id', '']]) {
      const { run, calls } = runner('{}')
      const result = await createProposals({ run }).act(id, action, {})
      expect(result.ok, `${id} ${action}`).toBe(false)
      expect(calls).toHaveLength(0)
    }
  })

  it('returns the list the store printed', async () => {
    const { run } = runner('{"proposals":[{"id":"a"}],"problems":[]}\n')
    expect(await createProposals({ run }).list()).toEqual({ ok: true, proposals: [{ id: 'a' }], problems: [] })
  })

  it('turns a crash, empty output or junk into a clear error instead of throwing', async () => {
    for (const r of [runner('', { err: new Error('boom'), stderr: 'Traceback: x' }), runner(''), runner('not json'), runner('[1,2]')]) {
      const list = await createProposals({ run: r.run }).list()
      expect(list.ok).toBe(false)
      expect(typeof list.error).toBe('string')
    }
  })

  it('passes through an action result, and a store refusal as an error', async () => {
    const ok = runner('{"ok":true,"proposal":{"id":"a","status":{"state":"snoozed"}}}')
    expect(await createProposals({ run: ok.run }).act('a', 'snooze', { days: 7 })).toEqual({ ok: true, proposal: { id: 'a', status: { state: 'snoozed' } } })
    const no = runner('{"ok":false,"error":"proposal a isn\'t open"}', { err: new Error('exit 1') })
    expect(await createProposals({ run: no.run }).act('a', 'dismiss', { reason: 'x' })).toEqual({ ok: false, error: "proposal a isn't open" })
  })

  it('non-object args become {} rather than reaching the CLI as something odd', () => {
    expect(proposalArgs('act', 'a', 'ticket', null).at(-1)).toBe('{}')
    expect(proposalArgs('act', 'a', 'ticket', 'rm -rf').at(-1)).toBe('{}')
  })
})
