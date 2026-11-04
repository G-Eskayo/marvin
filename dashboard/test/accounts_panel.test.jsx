import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'fs'
import path from 'path'
import AccountsPanel from '../src/components/AccountsPanel.jsx'
import { createAccounts } from '../electron/main/accounts.js'

// marvin#977: Gil's answer A, the Accounts card at the top of Health, always visible.
describe('the Accounts card on Health', () => {
  it('is mounted at the top of the Health checks, right under the overall badge', () => {
    const src = readFileSync(path.resolve(import.meta.dirname, '../src/components/HealthDashboard.jsx'), 'utf8')
    const badge = src.indexOf('<OverallBadge')
    expect(badge).toBeGreaterThan(0)
    expect(src.indexOf('<AccountsPanel />')).toBeGreaterThan(badge)
    expect(src.indexOf('<AccountsPanel />')).toBeLessThan(src.indexOf('coverage:'))
  })
  it('shows "Checking accounts" before the first answer, and nothing at all without the accounts API', () => {
    expect(renderToStaticMarkup(<AccountsPanel api={{ list: async () => ({}), renew: async () => ({}) }} />)).toContain('Checking accounts')
    expect(renderToStaticMarkup(<AccountsPanel api={null} />)).toBe('')
  })
  it('list() tells the card which machine is this one, saved or fresh, and on a failed fresh check', async () => {
    const read = () => JSON.stringify({ generated_at: 't', accounts: [{ id: 'github', machine: 'mac-mini-1', state: 'works' }] })
    const ok = createAccounts({ machine: () => 'macbook-pro-1', read, execFile: async () => ({ stdout: JSON.stringify({ accounts: [] }) }) })
    expect((await ok.list()).thisMachine).toBe('macbook-pro-1')
    expect((await ok.list({ fresh: true })).thisMachine).toBe('macbook-pro-1')
    const bad = createAccounts({ machine: () => 'macbook-pro-1', read, execFile: async () => { throw new Error('python missing') } })
    const v = await bad.list({ fresh: true })
    expect(v.thisMachine).toBe('macbook-pro-1')
    expect(v.freshProblem).toMatch(/python missing/)
  })
})
