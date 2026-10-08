/**
 * Tests for the ActivityBoard health status banner (issue #234).
 * Run via: npm test activity-banner.test.jsx
 */
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ActivityBoard from '../src/components/ActivityBoard.jsx'

describe('ActivityBoard health banner (#234)', () => {
  it('renders nothing when all three checks are green', () => {
    const healthStatus = {
      checks: [
        { id: 'pipeline:stopped', severity: 'green' },
        { id: 'sync:stuck', severity: 'green' },
        { id: 'deploy:missing', severity: 'green' }
      ]
    }
    const html = renderToStaticMarkup(
      <ActivityBoard healthStatus={healthStatus} onOpenMr={() => {}} onOpenDocs={() => {}} onOpenTicket={() => {}} />
    )
    expect(html).not.toContain('bg-red-950')
  })

  it('renders banner with pipeline:stopped red check', () => {
    const healthStatus = {
      checks: [
        {
          id: 'pipeline:stopped',
          severity: 'red',
          detail: 'Pipeline stopped since 19:38: measure:vitest-no-summary, 3 ticket(s). Clear: failure_breaker.py clear'
        }
      ]
    }
    const html = renderToStaticMarkup(
      <ActivityBoard healthStatus={healthStatus} onOpenMr={() => {}} onOpenDocs={() => {}} onOpenTicket={() => {}} />
    )
    expect(html).toContain('bg-red-950')
    expect(html).toContain('Pipeline stopped since 19:38')
    expect(html).toContain('3 ticket(s)')
  })

  it('renders banner with sync:stuck red check', () => {
    const healthStatus = {
      checks: [
        {
          id: 'sync:stuck:mac-mini:~/.agents',
          severity: 'red',
          detail: 'mac-mini ~/.agents not syncing since 10:41: leftover stash'
        }
      ]
    }
    const html = renderToStaticMarkup(
      <ActivityBoard healthStatus={healthStatus} onOpenMr={() => {}} onOpenDocs={() => {}} onOpenTicket={() => {}} />
    )
    expect(html).toContain('bg-red-950')
    expect(html).toContain('mac-mini ~/.agents not syncing since 10:41')
  })

  it('renders banner with deploy:missing red check', () => {
    const healthStatus = {
      checks: [
        {
          id: 'deploy:missing:snapshot-deploy',
          severity: 'red',
          detail: 'snapshot-deploy (#188): closed but launchd job never installed, no snapshot built'
        }
      ]
    }
    const html = renderToStaticMarkup(
      <ActivityBoard healthStatus={healthStatus} onOpenMr={() => {}} onOpenDocs={() => {}} onOpenTicket={() => {}} />
    )
    expect(html).toContain('bg-red-950')
    expect(html).toContain('snapshot-deploy')
    expect(html).toContain('#188')
    expect(html).toContain('launchd job never installed')
  })

  it('renders all three checks when all are red', () => {
    const healthStatus = {
      checks: [
        {
          id: 'pipeline:stopped',
          severity: 'red',
          detail: 'Pipeline stopped since 19:38: measure:vitest-no-summary, 3 ticket(s). Clear: failure_breaker.py clear'
        },
        {
          id: 'sync:stuck:mac-mini:~/.agents',
          severity: 'red',
          detail: 'mac-mini ~/.agents not syncing since 10:41: leftover stash'
        },
        {
          id: 'deploy:missing:snapshot-deploy',
          severity: 'red',
          detail: 'snapshot-deploy (#188): closed but launchd job never installed, no snapshot built'
        }
      ]
    }
    const html = renderToStaticMarkup(
      <ActivityBoard healthStatus={healthStatus} onOpenMr={() => {}} onOpenDocs={() => {}} onOpenTicket={() => {}} />
    )
    expect(html).toContain('bg-red-950')
    expect(html).toContain('Pipeline stopped since 19:38')
    expect(html).toContain('mac-mini ~/.agents not syncing')
    expect(html).toContain('snapshot-deploy')
  })

  it('ignores non-critical red checks (only shows pipeline:stopped, sync:stuck, deploy:missing)', () => {
    const healthStatus = {
      checks: [
        {
          id: 'token:oauth-token',
          severity: 'red',
          detail: 'some red check we ignore'
        },
        {
          id: 'pipeline:stopped',
          severity: 'red',
          detail: 'Pipeline stopped since 19:38: measure:vitest-no-summary, 3 ticket(s). Clear: failure_breaker.py clear'
        }
      ]
    }
    const html = renderToStaticMarkup(
      <ActivityBoard healthStatus={healthStatus} onOpenMr={() => {}} onOpenDocs={() => {}} onOpenTicket={() => {}} />
    )
    expect(html).toContain('Pipeline stopped since 19:38')
    expect(html).not.toContain('some red check we ignore')
  })

  it('handles missing healthStatus gracefully', () => {
    const html = renderToStaticMarkup(
      <ActivityBoard healthStatus={null} onOpenMr={() => {}} onOpenDocs={() => {}} onOpenTicket={() => {}} />
    )
    expect(html).not.toContain('bg-red-950')
  })
})
