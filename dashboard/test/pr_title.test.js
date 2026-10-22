import { describe, it, expect } from 'vitest'
import { displayTitle } from '../src/lib/pr_title'

describe('displayTitle', () => {
  it('returns the bare title when no ticket title is available', () => {
    const result = displayTitle('Implement G-Eskayo/marvin#123', null)
    expect(result).toBe('Implement G-Eskayo/marvin#123')
  })

  it('returns the bare title when ticket title is empty string', () => {
    const result = displayTitle('Implement G-Eskayo/marvin#123', '')
    expect(result).toBe('Implement G-Eskayo/marvin#123')
  })

  it('replaces bare implement title with ticket title', () => {
    const result = displayTitle('Implement G-Eskayo/marvin#123', 'Fix the cache bug')
    expect(result).toBe('Fix the cache bug')
  })

  it('replaces bare title from other repos with ticket title', () => {
    const result = displayTitle('Implement G-Eskayo/clarity-captions#42', 'Add offline mode')
    expect(result).toBe('Add offline mode')
  })

  it('preserves non-bare titles', () => {
    const result = displayTitle('Fix cache performance (#123)', 'Fix the cache bug')
    expect(result).toBe('Fix cache performance (#123)')
  })

  it('preserves manually-written PR titles even when ticket title exists', () => {
    const result = displayTitle('Stop retry storms: improve error handling', 'Retry mechanism redesign')
    expect(result).toBe('Stop retry storms: improve error handling')
  })

  it('works with repo names containing hyphens', () => {
    const result = displayTitle('Implement G-Eskayo/marvin-mobile#15', 'Add sign-in UI')
    expect(result).toBe('Add sign-in UI')
  })
})
