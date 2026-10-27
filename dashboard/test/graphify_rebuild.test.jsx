import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { rebuildCodeGraph } from '../electron/main/health.js'
import HealthDrilldown from '../src/components/HealthDrilldown.jsx'

// marvin#691: the code graph's freshness is a Health check, and its drill-down can rebuild the graph on the spot.
const graphCheck = { id: 'graphify:fresh', label: 'Code graph is current', severity: 'yellow', detail: '3 files changed since build abc1234', checked_at: null, value: 3 }

describe('rebuildCodeGraph', () => {
  it('runs the same refresh the git hooks run, on ~/.agents, then re-runs the health checks', async () => {
    const calls = []
    const exec = vi.fn(async (cmd, args) => { calls.push([cmd, ...args]); return { stdout: 'ok' } })
    const r = await rebuildCodeGraph(exec)
    expect(r.ok).toBe(true)
    expect(calls[0][0]).toMatch(/\.agents\/venv\/bin\/python$/)
    expect(calls[0].slice(1, 3)).toEqual([expect.stringMatching(/\.agents\/lib\/graphify_freshness\.py$/), 'refresh'])
    expect(calls[0][3]).toMatch(/\.agents$/)
    expect(calls[1][1]).toMatch(/health_checks\.py$/)
  })

  it('reports a failed rebuild instead of hiding it, and still refreshes Health so the card shows the error', async () => {
    const exec = vi.fn()
      .mockRejectedValueOnce(Object.assign(new Error('exit 1'), { stdout: 'graphify: command not found' }))
      .mockResolvedValueOnce({ stdout: '' })
    const r = await rebuildCodeGraph(exec)
    expect(r.ok).toBe(false)
    expect(r.output).toContain('command not found')
    expect(exec).toHaveBeenCalledTimes(2)
  })
})

describe('HealthDrilldown', () => {
  it('offers "Rebuild graph now" on the code graph check', () => {
    const html = renderToStaticMarkup(<HealthDrilldown check={graphCheck} onBack={() => {}} onRebuildGraph={() => {}} />)
    expect(html).toContain('Rebuild graph now')
  })

  it('shows no button on any other check', () => {
    const html = renderToStaticMarkup(<HealthDrilldown check={{ ...graphCheck, id: 'catalog:fresh' }} onBack={() => {}} onRebuildGraph={() => {}} />)
    expect(html).not.toContain('Rebuild graph now')
  })
})
