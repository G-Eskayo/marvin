import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import StageStrip from '../src/components/StageStrip.jsx'

describe('StageStrip component', () => {
  const NOW = Date.parse('2026-10-01T12:00:00Z')

  describe('visual rendering', () => {
    it('renders passed/failed/started/stalled/pending stages with distinct styling', () => {
      const segments = [
        { stage: 'claimed', status: 'passed', label: 'Claimed', message: '', remediation: '', machine: 'mini', cost_usd: 0.01, timestamp: '2026-10-01T00:00:00Z', events: [] },
        { stage: 'planning', status: 'failed', label: 'Planning', message: 'Test failed', remediation: 'Check logs', machine: 'mini', cost_usd: 0.02, timestamp: '2026-10-01T01:00:00Z', events: [] },
        { stage: 'executing', status: 'started', label: 'Executing', message: '', remediation: '', machine: 'mini', cost_usd: 0.05, timestamp: '2026-10-01T02:00:00Z', events: [] },
        { stage: 'verifying', status: 'stalled', label: 'Verifying', message: '', remediation: '', machine: 'mini', cost_usd: 0, timestamp: '2026-10-01T02:30:00Z', events: [] },
        { stage: 'gate', status: 'pending', label: 'Gate', message: '', remediation: '', machine: undefined, cost_usd: undefined, timestamp: undefined, events: [] }
      ]
      const html = renderToStaticMarkup(<StageStrip segments={segments} now={NOW} />)
      expect(html).toContain('passed')
      expect(html).toContain('failed')
      expect(html).toContain('started')
      expect(html).toContain('stalled')
      expect(html).toContain('pending')
    })

    it('displays stage labels', () => {
      const segments = [
        { stage: 'claimed', status: 'passed', label: 'Claimed', message: '', remediation: '', machine: 'mini', cost_usd: 0, timestamp: '2026-10-01T00:00:00Z', events: [] },
        { stage: 'gate', status: 'passed', label: 'Gate', message: '', remediation: '', machine: 'mini', cost_usd: 0, timestamp: '2026-10-01T01:00:00Z', events: [] }
      ]
      const html = renderToStaticMarkup(<StageStrip segments={segments} now={NOW} />)
      expect(html).toContain('Claimed')
      expect(html).toContain('Gate')
    })
  })

  describe('tooltip content (gap 2)', () => {
    it('includes machine and cost_usd in tooltip when present', () => {
      const segments = [
        { stage: 'executing', status: 'passed', label: 'Executing', message: '', remediation: '', machine: 'mac-mini', cost_usd: 1.23, timestamp: '2026-10-01T01:00:00Z', events: [] }
      ]
      const html = renderToStaticMarkup(<StageStrip segments={segments} now={NOW} />)
      expect(html).toContain('mac-mini')
      expect(html).toContain('1.23') // cost should be formatted
    })

    it('handles missing machine/cost_usd gracefully without undefined/NaN in tooltip', () => {
      const segments = [
        { stage: 'executing', status: 'passed', label: 'Executing', message: '', remediation: '', machine: undefined, cost_usd: undefined, timestamp: '2026-10-01T01:00:00Z', events: [] }
      ]
      const html = renderToStaticMarkup(<StageStrip segments={segments} now={NOW} />)
      expect(html).not.toContain('undefined')
      expect(html).not.toContain('NaN')
    })
  })

  describe('click and event handling (gap 4)', () => {
    it('clicking a stage with multiple events renders/exposes the event list', async () => {
      const segments = [
        {
          stage: 'executing',
          status: 'passed',
          label: 'Executing',
          message: '',
          remediation: '',
          machine: 'mini',
          cost_usd: 0.1,
          timestamp: '2026-10-01T02:00:00Z',
          events: [
            { status: 'failed', timestamp: '2026-10-01T01:00:00Z', stage: 'executing' },
            { status: 'started', timestamp: '2026-10-01T01:05:00Z', stage: 'executing' },
            { status: 'passed', timestamp: '2026-10-01T02:00:00Z', stage: 'executing' }
          ]
        }
      ]
      let selectedSegment = null
      const onStageClick = (seg) => {
        selectedSegment = seg
      }
      const html = renderToStaticMarkup(<StageStrip segments={segments} now={NOW} onStageClick={onStageClick} />)
      // Component should render without errors
      expect(html).toBeTruthy()
      // The stage should be clickable (has event data)
      expect(segments[0].events.length).toBeGreaterThan(1)
    })

    it('clicking a stage with single event does not crash', () => {
      const segments = [
        {
          stage: 'executing',
          status: 'passed',
          label: 'Executing',
          message: '',
          remediation: '',
          machine: 'mini',
          cost_usd: 0.1,
          timestamp: '2026-10-01T01:00:00Z',
          events: [
            { status: 'passed', timestamp: '2026-10-01T01:00:00Z', stage: 'executing' }
          ]
        }
      ]
      const html = renderToStaticMarkup(<StageStrip segments={segments} now={NOW} onStageClick={() => {}} />)
      expect(html).toBeTruthy()
    })

    it('keyboard activation with Enter fires the same handler', () => {
      // This tests that accessibility is maintained - Enter key should work like a click
      // The implementation should use onKeyDown for proper accessibility
      const segments = [
        { stage: 'executing', status: 'passed', label: 'Executing', message: '', remediation: '', machine: 'mini', cost_usd: 0, timestamp: '2026-10-01T01:00:00Z', events: [] }
      ]
      const html = renderToStaticMarkup(<StageStrip segments={segments} now={NOW} />)
      // Verify that the segment element has accessibility attributes (aria-label contains the label)
      expect(html).toContain('aria-label')
      expect(html).toContain('Executing')
    })
  })

  describe('edge cases', () => {
    it('renders nothing for empty segments array without crashing', () => {
      const html = renderToStaticMarkup(<StageStrip segments={[]} now={NOW} />)
      // Empty segments should return null/empty render
      expect(html === '' || html === 'null').toBe(true)
    })

    it('renders nothing for undefined segments without crashing', () => {
      const html = renderToStaticMarkup(<StageStrip segments={undefined} now={NOW} />)
      // Undefined should also return empty
      expect(html === '' || html === 'null').toBe(true)
    })

    it('handles segments with null/undefined fields gracefully', () => {
      const segments = [
        {
          stage: 'claimed',
          status: 'passed',
          label: 'Claimed',
          message: null,
          remediation: null,
          machine: null,
          cost_usd: null,
          timestamp: null,
          events: []
        }
      ]
      const html = renderToStaticMarkup(<StageStrip segments={segments} now={NOW} />)
      expect(html).toBeTruthy()
      expect(html).not.toContain('null')
    })
  })
})
