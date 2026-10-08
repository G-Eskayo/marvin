import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ActivityHealthBanner from '../src/components/ActivityHealthBanner.jsx'

describe('ActivityHealthBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders nothing when all checks are green', async () => {
    window.api = {
      health: {
        status: vi.fn().mockResolvedValue({
          checks: [
            { id: 'pipeline:stopped@mac-mini', severity: 'green', detail: 'not tripped' },
            { id: 'sync:stuck:mac-mini', severity: 'green', detail: 'no stashes' }
          ]
        })
      }
    }

    const { container } = render(<ActivityHealthBanner />)
    await waitFor(() => {
      expect(container.firstChild).toBeNull()
    })
  })

  it('renders red pipeline:stopped checks', async () => {
    window.api = {
      health: {
        status: vi.fn().mockResolvedValue({
          checks: [
            { id: 'pipeline:stopped@mac-mini', severity: 'red', detail: 'Pipeline stopped since 19:38: npm-build-failed, 3 tickets' }
          ]
        })
      }
    }

    render(<ActivityHealthBanner />)
    await waitFor(() => {
      expect(screen.getByText(/Pipeline stopped since/)).toBeInTheDocument()
    })
  })

  it('renders red sync:stuck checks', async () => {
    window.api = {
      health: {
        status: vi.fn().mockResolvedValue({
          checks: [
            { id: 'sync:stuck:mac-mini:.agents', severity: 'red', detail: 'mac-mini not syncing since 10:49: REFUSING to run' }
          ]
        })
      }
    }

    render(<ActivityHealthBanner />)
    await waitFor(() => {
      expect(screen.getByText(/REFUSING to run/)).toBeInTheDocument()
    })
  })

  it('renders red deploy:missing checks', async () => {
    window.api = {
      health: {
        status: vi.fn().mockResolvedValue({
          checks: [
            { id: 'deploy:missing:snapshot-deploy', severity: 'red', detail: 'missing snapshot-deploy plists. Run install script.' }
          ]
        })
      }
    }

    render(<ActivityHealthBanner />)
    await waitFor(() => {
      expect(screen.getByText(/missing snapshot-deploy/)).toBeInTheDocument()
    })
  })

  it('ignores non-red severity checks even if they match the IDs', async () => {
    window.api = {
      health: {
        status: vi.fn().mockResolvedValue({
          checks: [
            { id: 'pipeline:stopped@mac-mini', severity: 'yellow', detail: 'unreachable' },
            { id: 'sync:stuck:mac-mini', severity: 'yellow', detail: 'cannot verify' },
            { id: 'deploy:missing:snapshot-deploy', severity: 'yellow', detail: 'job never run' }
          ]
        })
      }
    }

    const { container } = render(<ActivityHealthBanner />)
    await waitFor(() => {
      expect(container.firstChild).toBeNull()
    })
  })

  it('ignores red checks with non-matching IDs', async () => {
    window.api = {
      health: {
        status: vi.fn().mockResolvedValue({
          checks: [
            { id: 'some:other:check', severity: 'red', detail: 'something else is broken' }
          ]
        })
      }
    }

    const { container } = render(<ActivityHealthBanner />)
    await waitFor(() => {
      expect(container.firstChild).toBeNull()
    })
  })

  it('renders multiple checks together', async () => {
    window.api = {
      health: {
        status: vi.fn().mockResolvedValue({
          checks: [
            { id: 'pipeline:stopped@mac-mini', severity: 'red', detail: 'Pipeline stopped since 19:38' },
            { id: 'sync:stuck:mac-mini:.agents', severity: 'red', detail: 'mac-mini not syncing since 10:49' }
          ]
        })
      }
    }

    render(<ActivityHealthBanner />)
    await waitFor(() => {
      expect(screen.getByText(/Pipeline stopped since/)).toBeInTheDocument()
      expect(screen.getByText(/mac-mini not syncing/)).toBeInTheDocument()
    })
  })

  it('handles health status API failure gracefully', async () => {
    window.api = {
      health: {
        status: vi.fn().mockRejectedValue(new Error('connection failed'))
      }
    }

    const { container } = render(<ActivityHealthBanner />)
    await waitFor(() => {
      expect(container.firstChild).toBeNull()
    })
  })
})
