import { describe, it, expect, vi } from 'vitest'
import { chooseBrain } from '../mobile-backend/brain_router.js'

describe('brain_router', () => {
  it('returns deep brain choice by default', async () => {
    const result = await chooseBrain('short text')
    expect(result).toEqual(expect.objectContaining({
      type: 'deep'
    }))
  })

  it('accepts abilities option', async () => {
    const result = await chooseBrain('text', { abilities: 'search,plan' })
    expect(result).toEqual(expect.objectContaining({
      type: expect.stringMatching(/^(fast|deep)$/)
    }))
  })

  it('includes brain-specific metadata', async () => {
    const result = await chooseBrain('test text')
    expect(result).toHaveProperty('type')
    expect(result).toHaveProperty('name')
  })

  it('handles error gracefully', async () => {
    // Test that an invalid input doesn't crash
    const result = await chooseBrain('')
    expect(result).toBeDefined()
    expect(result).toHaveProperty('type')
  })

  it('returns consistent type for same input', async () => {
    const result1 = await chooseBrain('test')
    const result2 = await chooseBrain('test')
    expect(result1.type).toBe(result2.type)
  })
})
