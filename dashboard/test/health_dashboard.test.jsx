import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { RecentErrors } from '../src/components/HealthDashboard.jsx'
import HealthDrilldown from '../src/components/HealthDrilldown.jsx'
import { redactPrivate } from '../src/lib/redact.js'

describe('HealthDashboard redaction', () => {
  // Test 19: CheckCard, RecentErrors, and HealthDrilldown redact private paths
  it('redactPrivate function redacts paths in check detail text', () => {
    const detail = 'Config at /Users/testuser/.config is valid'
    const redacted = redactPrivate(detail)
    expect(redacted).toContain('~/.config')
    expect(redacted).not.toContain('/Users/testuser')
  })

  it('RecentErrors redacts paths in message and raw fields', () => {
    const errors = [
      {
        machine: 'mac-mini-1',
        source: 'test-source',
        cause: 'File not found',
        count: 1,
        last_t: new Date().toISOString(),
        severity: 'red',
        message: 'Could not open /Users/testuser/file.txt',
        raw: 'Error: /Users/testuser/.cache/data missing'
      }
    ]
    const html = renderToStaticMarkup(<RecentErrors errors={errors} />)
    expect(html).toContain('Could not open')
    expect(html).toContain('~/file.txt')
    expect(html).toContain('~/.cache/data')
    expect(html).not.toContain('/Users/testuser')
  })

  it('HealthDrilldown redacts paths in check detail', () => {
    const check = {
      id: 'graphify:fresh',
      label: 'Code Graph Status',
      severity: 'yellow',
      checked_at: new Date().toISOString(),
      detail: 'Cache at /Users/testuser/.agents/cache needs refresh\nSee docs/plans/rebuild.md for details'
    }
    const onBack = () => {}
    const html = renderToStaticMarkup(<HealthDrilldown check={check} onBack={onBack} />)
    expect(html).toContain('~/.agents/cache')
    expect(html).toContain('docs/plans/…')
    expect(html).not.toContain('/Users/testuser')
  })
})
