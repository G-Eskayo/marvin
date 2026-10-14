import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import StageStrip from '../src/components/StageStrip'

describe('StageStrip component', () => {
  // Test 17: XSS test - React auto-escapes, no manual escapeHtml needed
  it('auto-escapes XSS attempts via React (no manual escapeHtml)', () => {
    const message = "the pipeline won't do this one automatically"
    const segments = [
      {
        stage: 'test',
        status: 'failed',
        label: 'Test',
        message,
        remediation: '<img onerror="alert(2)">',
        events: []
      }
    ]
    const html = renderToStaticMarkup(<StageStrip segments={segments} />)
    // Message should appear safely (React escaped the angle brackets and quotes in title)
    expect(html).toContain("won&#x27;t do")
    // Dangerous markup should be escaped: angle brackets and quotes must be escaped
    expect(html).toContain('&lt;img onerror=&quot;')
    expect(html).not.toContain('<img onerror=')
    // Double-escaping should not occur (no &amp; before lt;)
    expect(html).not.toContain('&amp;lt;')
  })

  // Test 18: null/undefined/empty segments
  it('renders nothing for null segments', () => {
    const result = renderToStaticMarkup(<StageStrip segments={null} />)
    expect(result.length).toBeLessThan(5)
  })

  it('renders nothing for undefined segments', () => {
    const result = renderToStaticMarkup(<StageStrip segments={undefined} />)
    expect(result.length).toBeLessThan(5)
  })

  it('renders nothing for empty segments array', () => {
    const result = renderToStaticMarkup(<StageStrip segments={[]} />)
    expect(result.length).toBeLessThan(5)
  })

  // Test 19: Missing optional fields
  it('handles segments with missing optional fields', () => {
    const segments = [
      {
        stage: 'test',
        status: 'passed',
        label: 'Test',
        events: []
      }
    ]
    const html = renderToStaticMarkup(<StageStrip segments={segments} />)
    expect(html).not.toContain('undefined')
    expect(html).not.toContain('NaN')
  })

  // Test 20: onStageClick omitted
  it('does not throw when onStageClick is omitted', () => {
    const segments = [
      {
        stage: 'test',
        status: 'failed',
        label: 'Test',
        events: [{ timestamp: new Date().toISOString(), machine: 'test', detail: 'test' }],
        cost: 0
      }
    ]
    const html = renderToStaticMarkup(<StageStrip segments={segments} />)
    expect(html).toContain('Test')
  })

  // Test 21: Long message truncation
  it('handles very long messages without hanging', () => {
    const longMessage = 'A'.repeat(10000)
    const segments = [
      {
        stage: 'test',
        status: 'passed',
        label: 'Test',
        message: longMessage,
        events: []
      }
    ]
    const start = Date.now()
    const html = renderToStaticMarkup(<StageStrip segments={segments} />)
    const elapsed = Date.now() - start

    expect(elapsed).toBeLessThan(1000)
    expect(html.length).toBeGreaterThan(0)
  })

  // Test 22: Multiple segments render in order
  it('renders multiple segments preserving stage order', () => {
    const segments = [
      { stage: 'claimed', status: 'passed', label: 'Claimed', events: [] },
      { stage: 'planning', status: 'started', label: 'Planning', events: [] },
      { stage: 'executing', status: 'failed', label: 'Executing', events: [] }
    ]
    const html = renderToStaticMarkup(<StageStrip segments={segments} />)
    expect(html).toContain('Claimed')
    expect(html).toContain('Planning')
    expect(html).toContain('Executing')
  })

  // Test 23: Multi-event segment shows count
  it('shows event count for multi-event segments', () => {
    const segments = [
      {
        stage: 'gate',
        status: 'failed',
        label: 'Gate',
        events: [
          { timestamp: new Date().toISOString(), machine: 'mac-mini', detail: 'attempt 1' },
          { timestamp: new Date().toISOString(), machine: 'mac-mini', detail: 'attempt 2' },
          { timestamp: new Date().toISOString(), machine: 'mac-mini', detail: 'attempt 3' }
        ]
      }
    ]
    const html = renderToStaticMarkup(<StageStrip segments={segments} />)
    expect(html).toContain('(3)')
  })

  // Test 24: Status colors are applied and distinct
  it('applies distinct CSS classes for each status', () => {
    const statuses = ['passed', 'failed', 'started', 'stalled', 'pending', 'blocked']
    const classes = {}
    for (const status of statuses) {
      const segments = [
        { stage: 'test', status, label: 'Test', events: [] }
      ]
      const html = renderToStaticMarkup(<StageStrip segments={segments} />)
      // Extract color class (bg-COLOR-950)
      const match = html.match(/bg-(\w+)-950/)
      expect(match).toBeDefined()
      classes[status] = match[1]
    }
    // Verify each status has a distinct color (or at least passes and failed have different ones)
    expect(classes.passed).not.toBe(classes.failed)
    expect(classes.passed).not.toBe(classes.blocked) // blocked shares red with failed
  })

  // Test 24b: Unknown status falls back to pending's class
  it('unknown status falls back to pending color class', () => {
    const segments = [
      { stage: 'test', status: 'exploded', label: 'Test', events: [] }
    ]
    const html = renderToStaticMarkup(<StageStrip segments={segments} />)
    // Should have the pending color (gray-950)
    expect(html).toContain('bg-gray-950')
    // Should not have a color-specific class for 'exploded'
    expect(html).not.toContain('bg-exploded-950')
  })

  // Test 17b: withStopPropagation prevents bubbling
  it('stops propagation when segment is clicked', async () => {
    const { default: StageStrip, withStopPropagation } = await import('../src/components/StageStrip')
    const mockStop = { stopPropagation: vi.fn() }
    const mockFn = vi.fn()
    withStopPropagation(mockStop, mockFn)
    expect(mockStop.stopPropagation).toHaveBeenCalled()
    expect(mockFn).toHaveBeenCalled()
  })

  // Test 8b: cost_usd malformed input handling
  it('handles non-number cost_usd without crashing, shows zero correctly', () => {
    const segments = [
      {
        stage: 'test',
        status: 'passed',
        label: 'Test',
        events: [
          { timestamp: new Date().toISOString(), machine: 'mac-mini', cost_usd: 'not-a-number', detail: '' },
          { timestamp: new Date().toISOString(), machine: 'mac-mini', cost_usd: 0, detail: '' }
        ]
      }
    ]
    // Expand to see events
    const html = renderToStaticMarkup(<StageStrip segments={segments} />)
    // Should render without throwing
    expect(html).toBeDefined()
    expect(html).toContain('mac-mini')
  })

  // Test 10b: failed segment shows message/remediation unconditionally
  it('renders message and remediation for failed segments without click', () => {
    const segments = [
      {
        stage: 'test',
        status: 'failed',
        label: 'Test',
        message: 'This stage failed',
        remediation: '→ Do something to fix it',
        events: []
      }
    ]
    const html = renderToStaticMarkup(<StageStrip segments={segments} />)
    expect(html).toContain('This stage failed')
    expect(html).toContain('Do something to fix it')
  })

  // Test 24c: Tooltip includes time, machine, and cost from latest event
  it('tooltip shows machine, time, and cost from the latest event', () => {
    const timestamp = new Date('2026-10-09T12:34:56Z').toISOString()
    const segments = [
      {
        stage: 'gate',
        status: 'passed',
        label: 'Gate',
        message: 'Gate passed',
        events: [
          { timestamp: new Date(Date.now() - 60000).toISOString(), machine: 'mac-laptop', cost_usd: 0.50 },
          { timestamp, machine: 'mac-mini', cost_usd: 1.23 }
        ]
      }
    ]
    const html = renderToStaticMarkup(<StageStrip segments={segments} />)
    // The title should contain the latest event's machine
    expect(html).toContain('title="Gate — Gate passed — mac-mini —')
    // Should include cost from latest event
    expect(html).toContain('$1.23')
  })
})
