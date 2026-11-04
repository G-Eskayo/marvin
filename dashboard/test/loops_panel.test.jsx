import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'fs'
import path from 'path'
import LoopsPanel, { LoopsView } from '../src/components/LoopsPanel.jsx'
import { loopsSummary, fixFor, cycleText, FIX_LABEL } from '../src/lib/loops_view.js'
import { createLoops } from '../electron/main/loops.js'

// marvin#1123: Vitals > Loops. Each loop: status, last full cycle, one fix.
const NOW = Date.parse('2026-11-04T12:00:00Z')
const row = (id, status, kind = 'rerun', extra = {}) => ({ id, name: id.toUpperCase(), status, owner: 'marvin', reason: `${id} reason`,
  last_cycle: status === 'closed' ? '2026-11-04T09:00:00Z' : null, fix: { level: 'one_tap', kind, arg: 'x' }, ...extra })

describe('the Loops view', () => {
  it('is a view of Health next to Checks, and App opens tickets inside the dashboard', () => {
    const src = readFileSync(path.resolve(import.meta.dirname, '../src/components/HealthDashboard.jsx'), 'utf8')
    expect(src).toContain("['loops', 'Loops']")
    expect(src).toContain('<LoopsPanel onOpenTicket={onOpenTicket} />')
    const app = readFileSync(path.resolve(import.meta.dirname, '../src/App.jsx'), 'utf8')
    expect(app).toMatch(/<HealthDashboard nav=\{nav\} onOpenTicket=\{\(repo, number\) => openItem\(repo, number, 'ticket'\)\} \/>/)
  })
  it('lists worst first, with a fix button on every loop that is not closed', () => {
    const view = { loops: [row('ok', 'closed'), row('w', 'not_wired', 'ticket'), row('b', 'broken'), row('s', 'stalled', 'relogin')] }
    const html = renderToStaticMarkup(<LoopsView view={view} filter="all" now={NOW} />)
    const order = ['data-loop="b"', 'data-loop="s"', 'data-loop="w"', 'data-loop="ok"'].map((m) => html.indexOf(m))
    expect(order).toEqual([...order].sort((a, b) => a - b))
    expect(html).toContain('>Re-run<')
    expect(html).toContain('>Re-login<')
    expect(html).toContain('>File ticket<')
    expect(html).toContain('last full cycle 3 h ago')
    expect((html.match(/data-fix=/g) || []).length).toBe(3)
    expect(html).toContain('1 broken')
  })
  it('hides closed loops under "Needs work" and shows them under All', () => {
    const view = { loops: [row('ok', 'closed'), row('b', 'broken')] }
    expect(renderToStaticMarkup(<LoopsView view={view} />)).not.toContain('data-loop="ok"')
    expect(renderToStaticMarkup(<LoopsView view={view} filter="all" />)).toContain('data-loop="ok"')
  })
  it('every fix kind in the registry has a label, and an unknown kind gets no button', () => {
    for (const k of ['rerun', 'relogin', 'install_job', 'rollback', 'ticket', 'decision']) expect(FIX_LABEL[k]).toBeTruthy()
    expect(fixFor(row('x', 'broken', 'shell'))).toBeNull()
    expect(fixFor(row('x', 'closed'))).toBeNull()
  })
  it('drops rows it cannot read and says how many registry entries are broken', () => {
    const view = { loops: [null, 5, { id: 'x', status: 'weird' }, row('b', 'broken')], problems: [{ loop: 'bad-one', error: 'e' }] }
    expect(loopsSummary(view).rows.map((r) => r.id)).toEqual(['b'])
    expect(renderToStaticMarkup(<LoopsView view={view} />)).toContain('bad-one')
  })
  it('escapes hostile text from the registry', () => {
    const html = renderToStaticMarkup(<LoopsView view={{ loops: [row('b', 'broken', 'rerun', { name: '<script>x</script>', reason: '<img onerror=1>' })] }} />)
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<img')
  })
  it('a missing view or API is calm', () => {
    expect(renderToStaticMarkup(<LoopsView view={null} />)).toContain('No loops yet')
    expect(renderToStaticMarkup(<LoopsPanel api={null} />)).toBe('')
    expect(cycleText('garbage', NOW)).toBe('no full cycle seen')
  })
})

describe('the loops IPC', () => {
  it('passes only a valid loop id to the fixed command', async () => {
    const calls = []
    const l = createLoops({ py: 'PY', script: 'L', execFile: async (f, a) => { calls.push([f, ...a]); return { stdout: '{"ok":true,"how":"run"}' } } })
    for (const bad of ['../x', 'a b', '', 'X', 'x;rm -rf ~', null, 5, 'a'.repeat(60)]) expect((await l.fix(bad)).ok).toBe(false)
    expect(calls).toEqual([])
    await l.fix('disk')
    await l.status()
    expect(calls).toEqual([['PY', 'L', 'fix', 'disk'], ['PY', 'L', 'status']])
  })
  it('a re-login goes through the Accounts renew flow', async () => {
    const renewed = []
    const l = createLoops({ execFile: async () => ({ stdout: '{"ok":true,"how":"renew","account":"github-token"}' }), renew: async (a) => { renewed.push(a); return { started: true } } })
    expect((await l.fix('logins')).says).toMatch(/Renewing/)
    expect(renewed).toEqual(['github-token'])
  })
  it('a fix that fails (exit 1 with JSON) or a missing python is reported, never thrown', async () => {
    const f = createLoops({ execFile: async () => { const e = new Error('exit 1'); e.stdout = '{"ok":false,"error":"Could not find service"}'; throw e } })
    expect(await f.fix('disk')).toEqual({ ok: false, error: 'Could not find service' })
    const m = createLoops({ execFile: async () => { throw new Error('ENOENT') } })
    expect((await m.fix('disk')).error).toMatch(/ENOENT/)
    expect((await m.status()).problem).toMatch(/ENOENT/)
  })
})
