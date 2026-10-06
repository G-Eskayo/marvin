import { describe, it, expect } from 'vitest'
import { buildReadiness } from '../electron/main/project_readiness.js'

describe('buildReadiness', () => {
  it('sorts projects worst-state-first', () => {
    const files = [
      {
        name: 'ok.json',
        content: JSON.stringify({
          repo: 'test/ok',
          generated_at: '2026-10-06T12:00:00Z',
          plan: {
            profile: { state: 'ok', reason: 'ok' },
            stack: { state: 'ok', reason: 'ok' }
          }
        })
      },
      {
        name: 'missing.json',
        content: JSON.stringify({
          repo: 'test/missing',
          generated_at: '2026-10-06T12:00:00Z',
          plan: {
            profile: { state: 'missing', reason: 'not found' }
          }
        })
      },
      {
        name: 'needs-human.json',
        content: JSON.stringify({
          repo: 'test/needs-human',
          generated_at: '2026-10-06T12:00:00Z',
          plan: {
            stack: { state: 'needs-human', reason: 'ambiguous' }
          }
        })
      }
    ]

    const result = buildReadiness({ files })

    expect(result).toHaveLength(3)
    expect(result[0].name).toBe('missing')
    expect(result[1].name).toBe('needs-human')
    expect(result[2].name).toBe('ok')
  })

  it('handles error-shaped files', () => {
    const files = [
      {
        name: 'error.json',
        content: JSON.stringify({
          repo: 'test/error',
          generated_at: '2026-10-06T12:00:00Z',
          error: 'inspect failed: network timeout'
        })
      }
    ]

    const result = buildReadiness({ files })

    expect(result).toHaveLength(1)
    expect(result[0].error).toBe('inspect failed: network timeout')
    expect(result[0].worstState).toBe('error')
  })

  it('extracts repo names correctly', () => {
    const files = [
      {
        name: 'marvin.json',
        content: JSON.stringify({
          repo: 'G-Eskayo/marvin',
          generated_at: '2026-10-06T12:00:00Z',
          plan: {}
        })
      }
    ]

    const result = buildReadiness({ files })

    expect(result[0].repo).toBe('G-Eskayo/marvin')
    expect(result[0].name).toBe('marvin')
  })

  it('ignores malformed files', () => {
    const files = [
      {
        name: 'ok.json',
        content: JSON.stringify({
          repo: 'test/ok',
          generated_at: '2026-10-06T12:00:00Z',
          plan: { piece: { state: 'ok', reason: 'ok' } }
        })
      },
      {
        name: 'broken.json',
        content: 'not json at all'
      }
    ]

    const result = buildReadiness({ files })

    expect(result).toHaveLength(1)
    expect(result[0].name).toBe('ok')
  })

  it('computes piece statistics correctly', () => {
    const files = [
      {
        name: 'test.json',
        content: JSON.stringify({
          repo: 'test/multi',
          generated_at: '2026-10-06T12:00:00Z',
          plan: {
            profile: { state: 'ok', reason: 'exists' },
            stack: { state: 'ok', reason: 'detected' },
            board: { state: 'missing', reason: 'not registered' },
            ci: { state: 'needs-human', reason: 'ambiguous' }
          }
        })
      }
    ]

    const result = buildReadiness({ files })

    expect(result[0].pieces).toHaveProperty('profile')
    expect(result[0].pieces.profile).toEqual({ state: 'ok', reason: 'exists' })
    expect(result[0].worstState).toBe('needs-human') // worst is needs-human (requires decision)
  })

  it('handles empty files array', () => {
    const result = buildReadiness({ files: [] })
    expect(result).toEqual([])
  })

  it('normalizes all unknown states to "unknown"', () => {
    const files = [
      {
        name: 'test.json',
        content: JSON.stringify({
          repo: 'test/unknown',
          generated_at: '2026-10-06T12:00:00Z',
          plan: {
            piece: { state: 'weird-state', reason: 'test' }
          }
        })
      }
    ]

    const result = buildReadiness({ files })

    expect(result[0].pieces.piece.state).toBe('unknown')
  })
})
