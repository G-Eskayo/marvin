import { describe, it, expect } from 'vitest'
import { readAccountsStatus, mergeLocal, renewPlan, createAccounts, RENEWABLE } from '../electron/main/accounts.js'

const row = (id, machine = 'mac-mini-1', extra = {}) => ({ id, machine, state: 'works', renew: { how: 'tab', command: `~/.agents/bin/marvin-renew ${id}` }, ...extra })
const statusText = (accounts) => JSON.stringify({ generated_at: '2026-10-30T12:00:00+00:00', by: 'mac-mini-1', accounts })

describe('readAccountsStatus: the saved view, never a crash', () => {
  it('missing and damaged files are an empty view that says why', () => {
    expect(readAccountsStatus('/x', () => { throw Object.assign(new Error('no'), { code: 'ENOENT' }) }).problem).toBe('missing')
    for (const bad of ['{trunc', 'null', '{"accounts": "x"}', '[]']) expect(readAccountsStatus('/x', () => bad).problem).toBe('unreadable')
    expect(readAccountsStatus('/x', () => statusText([row('tailscale'), null, { id: 5 }])).accounts).toHaveLength(1)
  })
  it('computes ageS and stale from generated_at and tolerance_s, not hardcoded null/false', () => {
    const now = Date.now()
    const secondsAgo = 30
    const isoTime = new Date(now - secondsAgo * 1000).toISOString()
    const stamped = JSON.stringify({ generated_at: isoTime, by: 'test', accounts: [row('test')], tolerance_s: 60 })
    const result = readAccountsStatus('/x', () => stamped)
    expect(result.copy.ageS).toBe(secondsAgo)
    expect(result.copy.stale).toBe(false)  // 30 sec < 60 sec tolerance
    const staleText = JSON.stringify({ generated_at: new Date(now - 100 * 1000).toISOString(), by: 'test', accounts: [row('test')], tolerance_s: 60 })
    const staleResult = readAccountsStatus('/x', () => staleText)
    expect(staleResult.copy.ageS).toBe(100)
    expect(staleResult.copy.stale).toBe(true)  // 100 sec > 60 sec tolerance
  })
  it('legacy files without tolerance_s use ACCOUNTS_TOLERANCE_S (1200), not hardcoded 600', () => {
    const now = Date.now()
    // 700 sec old: stale with old hardcoded 600 tolerance, fresh with ACCOUNTS_TOLERANCE_S (1200)
    const isoTime = new Date(now - 700 * 1000).toISOString()
    const legacyText = JSON.stringify({ generated_at: isoTime, by: 'test', accounts: [row('test')] })
    const result = readAccountsStatus('/x', () => legacyText)
    expect(result.copy.ageS).toBe(700)
    expect(result.copy.stale).toBe(false)  // 700 sec < 1200 sec tolerance (with ACCOUNTS_TOLERANCE_S)
    // Very old file (1500 sec) is stale with the new tolerance
    const veryOldText = JSON.stringify({ generated_at: new Date(now - 1500 * 1000).toISOString(), by: 'test', accounts: [row('test')] })
    const oldResult = readAccountsStatus('/x', () => veryOldText)
    expect(oldResult.copy.stale).toBe(true)  // 1500 sec > 1200 sec tolerance
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
  it('list with fresh=false and peers reads the producer copy instead of the stale local file', async () => {
    const freshResult = { value: { generated_at: '2026-10-30T12:00:00+00:00', by: 'mac-mini-1', accounts: [row('claude-setup-token', 'mac-mini-1')] }, ageS: 0, stale: false, from: 'mac-mini-1' }
    const peers = { read: async (name, path, opts) => { return { ...freshResult, value: { ...freshResult.value, accounts: [{ ...freshResult.value.accounts[0], state: 'expiring' }] } } } }
    const a = createAccounts({ machine: () => 'mac-mini-1', read: () => saved, peers, execFile: async () => ({ stdout: '{}' }) })
    const result = await a.list({ fresh: false })
    // Should have fetched from peers, showing 'expiring' state, not the saved 'works' state
    expect(result.accounts[0].state).toBe('expiring')
    expect(result.copy.from).toBe('mac-mini-1')
  })
  it('list with fresh=true and peers uses readAccountsStatusFresh for the saved view, not stale local read', async () => {
    // This ensures fresh=true doesn't ignore peers and read a stale local file
    const producerSavedView = { value: { generated_at: '2026-10-30T12:00:00+00:00', by: 'mac-mini-1', accounts: [row('tailscale', 'mac-mini-2012', { state: 'failed' })] }, ageS: 5, stale: false, from: 'mac-mini-1' }
    const freshCheckResult = { accounts: [row('tailscale', 'whatever', { state: 'works' })] }
    const peers = { read: async (name, path, opts) => producerSavedView }
    const a = createAccounts({
      machine: () => 'mac-mini-1',
      read: () => saved,
      peers,
      execFile: async () => ({ stdout: JSON.stringify(freshCheckResult) })
    })
    const result = await a.list({ fresh: true })
    // Should have merged fresh check into producer's saved view (which had mac-mini-2012), not just the local file
    expect(result.accounts).toHaveLength(2)  // both machines: fresh mac-mini-1 and producer's mac-mini-2012
    expect(result.accounts.find((r) => r.machine === 'mac-mini-1').state).toBe('works')
    expect(result.accounts.find((r) => r.machine === 'mac-mini-2012').state).toBe('failed')
  })
})
