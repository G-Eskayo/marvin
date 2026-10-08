import { render, screen, waitFor } from 'vitest'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import ModelsPanel from '../src/components/ModelsPanel'

describe('ModelsPanel', () => {
  beforeEach(() => {
    // Mock window.api.models.list
    window.api = {
      models: {
        list: vi.fn()
      }
    }
  })

  it('renders the panel with heading', () => {
    window.api.models.list.mockResolvedValue({
      models: [],
      error: null
    })

    render(<ModelsPanel />)
    expect(screen.getByText(/Models/i)).toBeTruthy()
  })

  it('displays registry models when loaded', async () => {
    window.api.models.list.mockResolvedValue({
      models: [
        {
          name: 'qwen2.5:14b',
          size_gb: 9.0,
          capability: 'local-classify-large',
          used_by: ['paper-dive'],
          last_used: '2026-10-08T12:00:00+00:00',
          heavy: true
        },
        {
          name: 'nomic-embed-text',
          size_gb: 0.27,
          capability: 'local-embed',
          used_by: ['core'],
          last_used: null,
          heavy: false
        }
      ],
      error: null
    })

    render(<ModelsPanel />)

    // Initially shows loading, then models
    await waitFor(() => {
      expect(screen.getByText('qwen2.5:14b')).toBeTruthy()
      expect(screen.getByText('nomic-embed-text')).toBeTruthy()
    })
  })

  it('separates heavy and light models', async () => {
    window.api.models.list.mockResolvedValue({
      models: [
        {
          name: 'FLUX.1-schnell-4bit',
          size_gb: 6.5,
          capability: 'image-gen',
          used_by: ['portfolio_flux'],
          last_used: null,
          heavy: true
        },
        {
          name: 'qwen2.5:7b',
          size_gb: 4.7,
          capability: 'local-classify-medium',
          used_by: ['paper-dive'],
          last_used: null,
          heavy: false
        }
      ],
      error: null
    })

    render(<ModelsPanel />)

    await waitFor(() => {
      // Heavy models section
      expect(screen.getByText(/Heavy Models/i)).toBeTruthy()
      // Light models section
      expect(screen.getByText(/Local Models/i)).toBeTruthy()
    })
  })

  it('displays error message on failure', async () => {
    window.api.models.list.mockResolvedValue({
      models: null,
      error: 'Failed to load registry'
    })

    render(<ModelsPanel />)

    await waitFor(() => {
      expect(screen.getByText(/Failed to load registry/i)).toBeTruthy()
    })
  })

  it('toggles visibility with button', async () => {
    window.api.models.list.mockResolvedValue({
      models: [
        {
          name: 'test-model',
          size_gb: 1.0,
          capability: 'test',
          used_by: [],
          last_used: null,
          heavy: false
        }
      ],
      error: null
    })

    render(<ModelsPanel />)

    // Panel starts closed
    expect(screen.queryByText('test-model')).toBeFalsy()

    // Click to open
    const button = screen.getByText(/show/i)
    button.click()

    await waitFor(() => {
      expect(screen.getByText('test-model')).toBeTruthy()
    })
  })

  it('displays model count in header', async () => {
    window.api.models.list.mockResolvedValue({
      models: [
        { name: 'model1', size_gb: 1.0, capability: 'test', used_by: [], last_used: null, heavy: false },
        { name: 'model2', size_gb: 2.0, capability: 'test', used_by: [], last_used: null, heavy: false }
      ],
      error: null
    })

    render(<ModelsPanel />)

    await waitFor(() => {
      expect(screen.getByText(/2 registered/i)).toBeTruthy()
    })
  })
})
