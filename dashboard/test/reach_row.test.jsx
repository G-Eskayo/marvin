import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'fs'
import path from 'path'
import ReachRow, { ReachView, channelWord } from '../src/components/ReachRow.jsx'
import { createAlerts } from '../electron/main/alerts.js'

// marvin#1123: Vitals' "Can MARVIN reach you?" row, from the one alert path's run log, with a test alert.
const NOW = Date.parse('2026-11-04T12:00:00Z')
const last = (channels, status = 'passed') => ({ verdict: status === 'failed' ? 'unreachable' : 'reachable',
  last: { at: '2026-11-04T11:50:00Z', title: 'MARVIN: sync is red', status, channels } })

describe('Can MARVIN reach you?', () => {
  it('is mounted in Health above the Accounts card', () => {
    const src = readFileSync(path.resolve(import.meta.dirname, '../src/components/HealthDashboard.jsx'), 'utf8')
    expect(src.indexOf('<ReachRow />')).toBeGreaterThan(src.indexOf('<OverallBadge'))
    expect(src.indexOf('<ReachRow />')).toBeLessThan(src.indexOf('<AccountsPanel />'))
  })
  it('shows each channel\'s real result, and the phone as waiting for #958', () => {
    const html = renderToStaticMarkup(<ReachView now={NOW} view={last({ desktop: 'sent', dashboard: 'failed: OSError: Connection refused', phone: 'not set up (waits for MARVIN Mobile push, #958)' })} />)
    expect(html).toContain('Yes')
    expect(html).toContain('10 min ago')
    expect(html).toMatch(/data-channel="desktop" data-ok="true"/)
    expect(html).toMatch(/data-channel="dashboard" data-ok="false"/)
    expect(html).toContain('Connection refused')
    expect(html).toMatch(/data-channel="phone" data-ok="null"/)
  })
  it('says No when the last alert reached nothing, and Not known before any alert', () => {
    expect(renderToStaticMarkup(<ReachView view={last({ desktop: 'failed: x', dashboard: 'failed: y', phone: 'not set up' }, 'failed')} />)).toContain('reached nothing')
    expect(renderToStaticMarkup(<ReachView view={{ verdict: 'unknown' }} />)).toContain('no alert sent')
    expect(renderToStaticMarkup(<ReachView view={null} />)).toContain('data-verdict="unknown"')
  })
  it('survives a hostile or broken view: unknown verdicts, missing channels, script in a title', () => {
    const html = renderToStaticMarkup(<ReachView view={{ verdict: '<img onerror=x>', last: { title: '<script>alert(1)</script>', channels: null } }} />)
    expect(html).not.toContain('<script>')
    expect(html).toContain('data-verdict="unknown"')
    expect(channelWord(undefined)).toEqual({ ok: false, text: 'no result' })
  })
  it('renders nothing without the alerts API', () => {
    expect(renderToStaticMarkup(<ReachRow api={null} />)).toBe('')
  })
})

describe('the alerts IPC', () => {
  it('runs only the fixed reach and test commands', async () => {
    const calls = []
    const a = createAlerts({ py: 'PY', script: 'MN', execFile: async (f, args) => { calls.push([f, ...args]); return { stdout: '{"verdict":"reachable","delivered":["desktop"]}' } } })
    await a.status()
    await a.test()
    expect(calls).toEqual([['PY', 'MN', 'reach'], ['PY', 'MN', 'test']])
  })
  it('a test alert that reached nothing still returns its channels (exit 1 with JSON)', async () => {
    const a = createAlerts({ execFile: async () => { const e = new Error('exit 1'); e.stdout = '{"delivered":[],"channels":{"desktop":"failed: x"}}'; throw e } })
    expect((await a.test()).channels.desktop).toBe('failed: x')
  })
  it('a missing python or garbage output is a problem, never a throw', async () => {
    const a = createAlerts({ execFile: async () => { throw new Error('ENOENT python') } })
    expect((await a.status()).problem).toMatch(/ENOENT/)
    expect((await a.test()).problem).toMatch(/ENOENT/)
    const g = createAlerts({ execFile: async () => ({ stdout: 'not json' }) })
    expect((await g.status()).verdict).toBe('unknown')
  })
})
