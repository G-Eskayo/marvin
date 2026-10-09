import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { StageStrip } from '../src/components/StageStrip.jsx'

describe('StageStrip component', () => {
  it('renders passed stages with checkmarks', () => {
    const now = new Date('2026-10-09T12:00:00Z').getTime()
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(now - 60 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      planning: { stage: 'planning', status: 'passed', timestamp: new Date(now - 50 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
    }
    const html = renderToStaticMarkup(<StageStrip stages={stages} isLiveNow={false} now={now} />)
    expect(html).toContain('Claimed')
    expect(html).toContain('Planning')
    expect(html).toContain('✓')
  })

  it('renders failed stage with X and message', () => {
    const now = new Date('2026-10-09T12:00:00Z').getTime()
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(now - 60 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
      gate: { stage: 'gate', status: 'failed', detail: 'GATE_TESTS_FAILED: some tests failed', timestamp: new Date(now - 10 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
    }
    const html = renderToStaticMarkup(<StageStrip stages={stages} isLiveNow={false} now={now} />)
    expect(html).toContain('✗')
    expect(html).toContain('Gate')
  })

  it('renders started stage with pulse', () => {
    const now = new Date('2026-10-09T12:00:00Z').getTime()
    const stages = {
      executing: { stage: 'executing', status: 'started', timestamp: new Date(now - 2 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
    }
    const html = renderToStaticMarkup(<StageStrip stages={stages} isLiveNow={true} now={now} />)
    expect(html).toContain('Executing')
    expect(html).toContain('⊚')
  })

  it('does not crash when stages is empty', () => {
    const now = new Date('2026-10-09T12:00:00Z').getTime()
    expect(() => renderToStaticMarkup(<StageStrip stages={{}} isLiveNow={false} now={now} />)).not.toThrow()
  })

  it('renders with onStageClick handler (no crash)', () => {
    const now = new Date('2026-10-09T12:00:00Z').getTime()
    const onClick = vi.fn()
    const stages = {
      claimed: { stage: 'claimed', status: 'passed', timestamp: new Date(now - 60 * 60 * 1000).toISOString(), machine: 'mac-mini-1' },
    }
    const html = renderToStaticMarkup(<StageStrip stages={stages} isLiveNow={false} now={now} onStageClick={onClick} />)
    expect(html).toContain('Claimed')
  })
})
