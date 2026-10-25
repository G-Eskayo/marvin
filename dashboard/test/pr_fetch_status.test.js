import { describe, it, expect } from 'vitest'
import { ago } from '../src/lib/pr_fetch_status.js'

describe('ago', () => {
  it('shows "just now" for times less than 30 seconds ago', () => {
    expect(ago(0)).toBe('just now')
    expect(ago(29_999)).toBe('just now')
  })

  it('shows minutes for times 30 seconds to 30 minutes ago', () => {
    expect(ago(30_000)).toBe('1 min ago')
    expect(ago(60_000)).toBe('1 min ago')
    expect(ago(120_000)).toBe('2 min ago')
    expect(ago(1_799_000)).toBe('30 min ago')
  })

  it('shows hours for times 60 minutes or more ago', () => {
    expect(ago(3_600_000)).toBe('1 h ago')
    expect(ago(7_200_000)).toBe('2 h ago')
    expect(ago(86_400_000)).toBe('24 h ago')
  })
})
