import { describe, it, expect, vi } from 'vitest'
import { enableAddon } from '../src/lib/addon_enable.js'

describe('enableAddon', () => {
  it('successfully enables an addon and returns features', async () => {
    const features = { portfolio: true }
    const api = {
      setFeature: vi.fn().mockResolvedValue(),
      features: vi.fn().mockResolvedValue(features)
    }
    const result = await enableAddon('portfolio', api)
    expect(result).toEqual({ features, error: null })
    expect(api.setFeature).toHaveBeenCalledWith('portfolio', true)
    expect(api.features).toHaveBeenCalled()
  })

  it('returns error message when setFeature throws', async () => {
    const api = {
      setFeature: vi.fn().mockRejectedValue(new Error('Config file is corrupted or invalid')),
      features: vi.fn()
    }
    const result = await enableAddon('portfolio', api)
    expect(result).toEqual({ features: null, error: 'Config file is corrupted or invalid' })
    expect(api.features).not.toHaveBeenCalled()
  })

  it('handles non-Error rejection with string message', async () => {
    const api = {
      setFeature: vi.fn().mockRejectedValue('String error'),
      features: vi.fn()
    }
    const result = await enableAddon('portfolio', api)
    expect(result).toEqual({ features: null, error: 'String error' })
  })

  it('when setFeature succeeds but features() rejects, surfaces that error', async () => {
    const api = {
      setFeature: vi.fn().mockResolvedValue(),
      features: vi.fn().mockRejectedValue(new Error('Failed to read features'))
    }
    const result = await enableAddon('portfolio', api)
    expect(result).toEqual({ features: null, error: 'Failed to read features' })
    expect(api.setFeature).toHaveBeenCalledWith('portfolio', true)
    expect(api.features).toHaveBeenCalled()
  })
})
