import { describe, it, expect } from 'vitest'
import { readAccountsStatus, readAccountsStatusFresh, mergeLocal, renewPlan, createAccounts, RENEWABLE, ACCOUNTS_TOLERANCE_S_MS } from '../electron/main/accounts.js'

const row = (id, machine = 'mac-mini-1', extra = {}) => ({ id, machine, state: 'works', renew: { how: 'tab', command: `~/.agents/bin/marvin-renew ${id}` }, ...extra })
const statusText = (accounts) => JSON.stringify({ generated_at: '2026-10-30T12:00:00+00:00', by: 'mac-mini-1', accounts })

describe('readAccountsStatus: the saved view, never a crash', () => {
  it('missing and damaged files are an empty view that says why', () => {
    expect(readAccountsStatus('/x', () => { throw Object.assign(new Error('no'), { code: 'ENOENT' }) }).problem).toBe('missing')
    for (const bad of ['{trunc', 'null', '{"accounts": "x"}', '[]']) expect(readAccountsStatus('/x', () => bad).problem).toBe('unreadable')
    expect(readAccountsStatus('/x', () => statusText([row('tailscale'), null, { id: 5 }])).accounts).toHaveLength(1)
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

describe('readAccountsStatusFresh', () => {
  it('uses peers.read to get the fresher of local or producer copy, with copy metadata', async () => {
    const mockCopy = {
      value: { accounts: [row('github-token')], generated_at: '2026-11-12T12:00:00Z', by: 'mac-mini-1' },
      host: 'mac-mini-1',
      ageS: 120,
      stale: false,
      legacy: false,
      toleranceS: 1200,
      from: 'local',
      missing: false
    }
    const peers = { read: async () => mockCopy }
    const result = await readAccountsStatusFresh(peers, '/fake')
    expect(result.accounts).toHaveLength(1)
    expect(result.copy).toMatchObject({ host: 'mac-mini-1', ageS: 120, stale: false, from: 'local' })
  })
  it('toleranceS defaults to accounts tolerance (20 min)', async () => {
    const peers = {
      read: async (name, path, { defaultToleranceS }) => {
        expect(defaultToleranceS).toBe(ACCOUNTS_TOLERANCE_S_MS / 1000)
        return { value: null, missing: true }
      }
    }
    await readAccountsStatusFresh(peers, '/fake')
  })
  it('handles missing or unreadable producer copies gracefully', async () => {
    const peers = { read: async () => ({ value: null, missing: true, ageS: null }) }
    const result = await readAccountsStatusFresh(peers, '/fake')
    expect(result.accounts).toEqual([])
    expect(result.problem).toBe('missing')
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
  it('with peers option, list uses readAccountsStatusFresh instead of readAccountsStatus', async () => {
    const mockPeers = {
      read: async () => ({
        value: { accounts: [row('github-token')], generated_at: '2026-11-12T12:00:00Z', by: 'mac-mini-1' },
        host: 'mac-mini-1',
        ageS: 60,
        stale: false,
        legacy: false,
        toleranceS: 1200,
        from: 'local',
        missing: false
      })
    }
    const a = createAccounts({ machine: () => 'mac-mini-1', peers: mockPeers, execFile: async () => ({ stdout: '' }) })
    const result = await a.list({ fresh: false })
    expect(result.copy).toBeDefined()
    expect(result.copy.from).toBe('local')
    expect(result.thisMachine).toBe('mac-mini-1')
  })
  it('with peers, fresh check still merges local over the peer copy', async () => {
    const mockPeers = {
      read: async () => ({
        value: { accounts: [row('github-token')], generated_at: '2026-11-12T12:00:00Z', by: 'mac-mini-1' },
        host: 'mac-mini-1',
        ageS: 60,
        stale: false,
        legacy: false,
        toleranceS: 1200,
        from: 'local',
        missing: false
      })
    }
    const a = createAccounts({
      machine: () => 'mac-mini-1',
      peers: mockPeers,
      execFile: async () => ({ stdout: JSON.stringify({ accounts: [row('tailscale', 'mac-mini-1', { state: 'failed' })] }) })
    })
    const result = await a.list({ fresh: true })
    expect(result.accounts.find((r) => r.id === 'tailscale').state).toBe('failed')
  })
  it('with peers: if peers.read throws, fall back to local copy with producerUnreachable flag', async () => {
    const mockPeers = {
      read: async () => { throw new Error('network error') }
    }
    const a = createAccounts({
      machine: () => 'mac-mini-1',
      peers: mockPeers,
      read: () => saved,
      execFile: async () => ({ stdout: '' })
    })
    const result = await a.list({ fresh: false })
    expect(result.accounts).toHaveLength(2)
    expect(result.copy).toBeDefined()
    expect(result.copy.producerUnreachable).toBe(true)
    expect(result.problem).toBeNull()
  })
  it('with peers: error during list still allows fresh check to proceed with local data', async () => {
    const mockPeers = {
      read: async () => { throw new Error('parse error') }
    }
    const a = createAccounts({
      machine: () => 'mac-mini-1',
      peers: mockPeers,
      read: () => saved,
      execFile: async () => ({ stdout: JSON.stringify({ accounts: [row('tailscale', 'mac-mini-1', { state: 'failed' })] }) })
    })
    const result = await a.list({ fresh: true })
    expect(result.accounts.find((r) => r.id === 'tailscale').state).toBe('failed')
    expect(result.copy.producerUnreachable).toBe(true)
  })
})
