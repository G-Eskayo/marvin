import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import StageStrip from '../src/components/StageStrip.jsx'

describe('StageStrip component', () => {
  const mockStrip = [
    {
      stage: 'claimed',
      status: 'passed',
      detail: 'Ticket claimed',
      remediation: null,
      when: 'Oct 15, 2026, 10:00 AM',
      money: '$0.00',
      timestamp: '2026-10-15T10:00:00Z',
      machine: 'mac-mini',
      liveStatus: null,
      needsRebase: false
    },
    {
      stage: 'gate',
      status: 'passed',
      detail: 'rebased and retested clean',
      remediation: null,
      when: 'Oct 15, 2026, 11:30 AM',
      money: '$0.05',
      timestamp: '2026-10-15T11:30:00Z',
      machine: 'mac-mini',
      liveStatus: null,
      needsRebase: false
    },
    {
      stage: 'merging',
      status: 'failed',
      detail: 'NOT_MERGEABLE: conflicts',
      remediation: 'Resolve the conflicts on GitHub',
      when: 'Oct 15, 2026, 12:00 PM',
      money: '$0.02',
      timestamp: '2026-10-15T12:00:00Z',
      machine: 'mac-mini',
      liveStatus: null,
      needsRebase: false
    }
  ]

  it('renders pills for each stage in the strip', () => {
    const html = renderToStaticMarkup(<StageStrip strip={mockStrip} />)
    expect(html).toContain('Claimed')
    expect(html).toContain('Merge gate')
    expect(html).toContain('Merging')
  })

  it('uses status icon: ✓ for passed, ✗ for failed', () => {
    const html = renderToStaticMarkup(<StageStrip strip={mockStrip} />)
    expect(html).toContain('✓')
    expect(html).toContain('✗')
  })

  it('includes stage titles in component output', () => {
    const html = renderToStaticMarkup(<StageStrip strip={mockStrip} />)
    expect(html).toContain('title="Claimed (passed)"')
  })

  it('renders rebase warning for REBASE_CONFLICT stages', () => {
    const conflictStrip = [
      {
        stage: 'gate',
        status: 'failed',
        detail: 'REBASE_CONFLICT: Rebase onto main failed',
        remediation: null,
        when: 'Oct 15, 2026, 11:30 AM',
        money: '$0.05',
        timestamp: '2026-10-15T11:30:00Z',
        machine: 'mac-mini',
        liveStatus: null,
        needsRebase: true
      }
    ]
    const html = renderToStaticMarkup(<StageStrip strip={conflictStrip} />)
    expect(html).toContain('⚠')
  })

  it('includes remediation data in stages that have it', () => {
    const stripWithRemediation = [
      {
        stage: 'merging',
        status: 'failed',
        detail: 'NOT_MERGEABLE: conflicts',
        remediation: 'Resolve the conflicts on GitHub',
        when: 'Oct 15, 2026, 12:00 PM',
        money: '$0.02',
        timestamp: '2026-10-15T12:00:00Z',
        machine: 'mac-mini',
        liveStatus: null,
        needsRebase: false
      }
    ]
    const html = renderToStaticMarkup(<StageStrip strip={stripWithRemediation} />)
    expect(html).toContain('Merging')
    expect(html).toContain('✗')
  })

  it('renders stalled indicator when liveStatus is stalled', () => {
    const stalledStrip = [
      {
        stage: 'executing',
        status: 'started',
        detail: 'Running tests',
        remediation: null,
        when: 'Oct 15, 2026, 10:00 AM',
        money: '$0.05',
        timestamp: '2026-10-15T10:00:00Z',
        machine: 'mac-mini',
        liveStatus: 'stalled',
        needsRebase: false
      }
    ]
    const html = renderToStaticMarkup(<StageStrip strip={stalledStrip} />)
    expect(html).toContain('●')
  })
})
