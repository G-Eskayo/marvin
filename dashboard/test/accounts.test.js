import { describe, it, expect } from 'vitest'
import { readAccountsStatus, readAccountsStatusFresh, mergeLocal, renewPlan, createAccounts, RENEWABLE } from '../electron/main/accounts.js'

const row = (id, machine = 'mac-mini-1', extra = {}) => ({ id, machine, state: 'works', renew: { how: 'tab', command: `~/.agents/bin/marvin-renew ${id}` }, ...extra })
const statusText = (accounts) => JSON.stringify({ generated_at: '2026-10-30T12:00:00+00:00', by: 'mac-mini-1', accounts })

describe('readAccountsStatus: the saved view, never a crash', () => {
  it('missing and damaged files are an empty view that says why', () => {
    expect(readAccountsStatus('/x', () => { throw Object.assign(new Error('no'), { code: 'ENOENT' }) }).problem).toBe('missing')
    for (const bad of ['{trunc', 'null', '{"accounts": "x"}', '[]']) expect(readAccountsStatus('/x', () => bad).problem).toBe('unreadable')
    expect(readAccountsStatus('/x', () => statusText([row('tailscale'), null, { id: 5 }])).accounts).toHaveLength(1)
  })
})

describe('readAccountsStatusFresh: peer read of the producer\'s live copy', () => {
  it('serves the producer\'s copy when read succeeds', async () => {
    const peers = { read: async () => ({ value: { generated_at: '2026-11-10T12:00:00Z', by: 'mac-mini-1', accounts: [row('tailscale')] }, from: 'mac-mini-1', ageS: 30, host: 'mac-mini-1', stale: false, legacy: false }) }
    const r = await readAccountsStatusFresh(peers)
    expect(r.accounts).toHaveLength(1)
    expect(r.copy.from).toBe('mac-mini-1')
    expect(r.copy.host).toBe('mac-mini-1')
    expect(r.copy.ageS).toBe(30)
  })

  it('returns empty with a problem when the read fails', async () => {
    const peers = { read: async () => ({ missing: true, ageS: 1200, toleranceS: 1200 }) }
    const r = await readAccountsStatusFresh(peers)
    expect(r.problem).toBe('missing')
    expect(r.accounts).toEqual([])
    expect(r.copy.stale).toBe(false)
  })

  it('marks as stale when ageS exceeds toleranceS', async () => {
    const peers = { read: async () => ({ value: { generated_at: '2026-11-10T12:00:00Z', by: 'mac-mini-1', accounts: [] }, from: 'mac-mini-1', ageS: 1500, stale: true, host: 'mac-mini-1', legacy: false, toleranceS: 1200 }) }
    const r = await readAccountsStatusFresh(peers)
    expect(r.copy.stale).toBe(true)
    expect(r.copy.toleranceS).toBe(1200)
  })

  it('notes when the producer is unreachable', async () => {
    const peers = { read: async () => ({ value: { generated_at: '2026-11-10T12:00:00Z', by: 'mac-mini-1', accounts: [] }, from: 'mac-mini-1', ageS: 0, host: null, producerUnreachable: true, stale: false, legacy: false }) }
    const r = await readAccountsStatusFresh(peers)
    expect(r.copy.producerUnreachable).toBe(true)
    expect(r.copy.host).toBeNull()
  })

  it('filters invalid rows like readAccountsStatus does', async () => {
    const peers = { read: async () => ({ value: { generated_at: '2026-11-10T12:00:00Z', by: 'mac-mini-1', accounts: [row('tailscale'), null, { id: 5 }, row('github-token')] }, from: 'mac-mini-1', ageS: 0, host: 'mac-mini-1', stale: false, legacy: false }) }
    const r = await readAccountsStatusFresh(peers)
    expect(r.accounts).toHaveLength(2)
    expect(r.accounts.every((a) => typeof a.id === 'string')).toBe(true)
  })

  it('preserves generated_at and by from the value', async () => {
    const peers = { read: async () => ({ value: { generated_at: '2026-11-10T11:30:00Z', by: 'mac-mini-2012', accounts: [] }, from: 'mac-mini-1', ageS: 30, host: 'mac-mini-1', stale: false, legacy: false }) }
    const r = await readAccountsStatusFresh(peers)
    expect(r.generatedAt).toBe('2026-11-10T11:30:00Z')
    expect(r.by).toBe('mac-mini-2012')
  })
})

describe('mergeLocal: a fresh check of this machine replaces only its rows', () => {
  it('keeps the other machines, swaps this one', () => {
    const saved = { accounts: [row('tailscale', 'mac-mini-1', { state: 'failed' }), row('tailscale', 'mac-mini-2012')] }
    const out = mergeLocal(saved, { accounts: [row('tailscale', 'whatever', { state: 'works' })] }, 'mac-mini-1')
    expect(out.accounts.map((r) => `${r.machine}:${r.state}`).sort()).toEqual(['mac-mini-1:works', 'mac-mini-2012:works'])
    expect(mergeLocal(saved, { accounts: [] }, 'mac-mini-1')).toBe(saved)
    expect(mergeLocal(saved, 'garbage', 'mac-mini-1')).toBe(saved)
  })
})

describe('renewPlan: what Renew does, as data', () => {
  it('a renewable account on this machine opens a labelled helper tab with fixed argv', () => {
    const p = renewPlan(row('claude-setup-token'), 'mac-mini-1')
    expect(p.how).toBe('tab')
    expect(p.argv.slice(1, 5)).toEqual(['--group', 'Accounts', '--title', 'Renew Claude setup-token'])
    expect(p.argv.slice(-2)[1]).toBe('claude-setup-token')
    expect(p.argv.at(-2)).toMatch(/bin\/marvin-renew$/)
  })
  it('an account on another machine shows the command and where, never a tab here', () => {
    expect(renewPlan(row('github-token', 'macbook-pro-1'), 'mac-mini-1')).toEqual({ how: 'command', command: '~/.agents/bin/marvin-renew github', where: 'macbook-pro-1' })
  })
  it('accounts with no safe one-tap fix show their exact command', () => {
    const p = renewPlan({ id: 'tailscale', machine: 'mac-mini-2012', renew: { how: 'command', command: 'sudo tailscale up --force-reauth', where: 'this machine' } }, 'mac-mini-1')
    expect(p).toEqual({ how: 'command', command: 'sudo tailscale up --force-reauth', where: 'this machine' })
  })
  it('nothing the renderer sends ends up in argv: only the fixed table', () => {
    for (const p of Object.values(RENEWABLE)) expect(p).toMatch(/^[a-z-]+$/)
    expect(renewPlan(null, 'm')).toBeNull()
  })
})

describe('createAccounts', () => {
  const saved = statusText([row('claude-setup-token'), row('tailscale', 'mac-mini-2012', { renew: { how: 'command', command: 'sudo tailscale up', where: 'mac-mini-2012' } })])
  it('renew runs helper-tab with the planned argv and returns no secret, just that it started', async () => {
    const calls = []
    const a = createAccounts({ machine: () => 'mac-mini-1', read: () => saved, execFile: async (bin, args) => { calls.push([bin, ...args]); return { stdout: '7' } } })
    const out = await a.renew('claude-setup-token')
    expect(out).toEqual({ how: 'tab', title: 'Renew Claude setup-token', steps: null, started: true })
    expect(calls).toHaveLength(1)
    expect(calls[0][0]).toMatch(/bin\/helper-tab$/)
  })
  it('unknown ids and shell metacharacters are refused before anything runs', async () => {
    const calls = []
    const a = createAccounts({ machine: () => 'mac-mini-1', read: () => saved, execFile: async (...x) => { calls.push(x); return { stdout: '' } } })
    for (const bad of ['evil; touch PWNED', '../x', '', 'nope']) await expect(a.renew(bad)).rejects.toThrow('unknown account')
    expect(calls).toEqual([])
  })
  it('a command-only account returns its command and runs nothing', async () => {
    const calls = []
    const a = createAccounts({ machine: () => 'mac-mini-1', read: () => saved, execFile: async (...x) => { calls.push(x); return { stdout: '' } } })
    expect(await a.renew('tailscale', 'mac-mini-2012')).toEqual({ how: 'command', command: 'sudo tailscale up', where: 'mac-mini-2012' })
    expect(calls).toEqual([])
  })
  it('list: saved first; fresh merges this machine, and a failing fresh check keeps the saved view and says why', async () => {
    const ok = createAccounts({ machine: () => 'mac-mini-1', read: () => saved, execFile: async () => ({ stdout: JSON.stringify({ accounts: [row('claude-setup-token', 'x', { state: 'failed' })] }) }) })
    expect((await ok.list()).accounts.find((r) => r.id === 'claude-setup-token').state).toBe('works')
    expect((await ok.list({ fresh: true })).accounts.find((r) => r.id === 'claude-setup-token').state).toBe('failed')
    const bad = createAccounts({ machine: () => 'mac-mini-1', read: () => saved, execFile: async () => { throw new Error('timeout\nmore') } })
    const v = await bad.list({ fresh: true })
    expect(v.accounts).toHaveLength(2)
    expect(v.freshProblem).toBe('timeout')
  })

  it('list: when peers is supplied, reads from the peer copy and includes copy metadata', async () => {
    const peers = { read: async () => ({ value: { generated_at: '2026-11-10T12:00:00Z', by: 'mac-mini-1', accounts: [row('tailscale')] }, from: 'mac-mini-1', ageS: 30, host: 'mac-mini-1', stale: false, legacy: false }) }
    const a = createAccounts({ machine: () => 'mac-mini-1', execFile: async () => ({ stdout: '{}' }), peers })
    const v = await a.list()
    expect(v.accounts).toHaveLength(1)
    expect(v.copy.from).toBe('mac-mini-1')
    expect(v.thisMachine).toBe('mac-mini-1')
    expect(v.problem).toBeUndefined()
  })
})
