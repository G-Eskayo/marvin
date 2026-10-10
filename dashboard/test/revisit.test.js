import { describe, it, expect } from 'vitest'
import { parseRevisitComment, latestRevisit } from '../src/lib/revisit.js'

describe('parseRevisitComment', () => {
  it('parses date-only format', () => {
    const comment = { body: 'Revisit by: 2026-10-15' }
    expect(parseRevisitComment(comment)).toEqual({ date: '2026-10-15', condition: null })
  })

  it('parses date with em-dash condition', () => {
    const comment = { body: 'Revisit by: 2026-10-15 — #123 closes' }
    expect(parseRevisitComment(comment)).toEqual({ date: '2026-10-15', condition: '#123 closes' })
  })

  it('parses date with hyphen condition', () => {
    const comment = { body: 'Revisit by: 2026-10-15 - some condition' }
    expect(parseRevisitComment(comment)).toEqual({ date: '2026-10-15', condition: 'some condition' })
  })

  it('extracts ticket reference from condition', () => {
    const comment = { body: 'Revisit by: 2026-10-15 — When #456 is done' }
    expect(parseRevisitComment(comment)).toEqual({ date: '2026-10-15', condition: 'When #456 is done' })
  })

  it('is case-insensitive', () => {
    const comment = { body: 'REVISIT BY: 2026-10-15' }
    expect(parseRevisitComment(comment)).toEqual({ date: '2026-10-15', condition: null })
  })

  it('returns null for non-matching text', () => {
    const comment = { body: 'let me revisit this later' }
    expect(parseRevisitComment(comment)).toBeNull()
  })

  it('returns null for malformed date', () => {
    const comment = { body: 'Revisit by: 2026-13-32' }
    expect(parseRevisitComment(comment)).toBeNull()
  })

  it('returns null for missing body', () => {
    expect(parseRevisitComment({})).toBeNull()
    expect(parseRevisitComment(null)).toBeNull()
  })

  it('handles date at the start of the body', () => {
    const comment = { body: 'Revisit by: 2026-10-20 — fix security issue' }
    expect(parseRevisitComment(comment)).toEqual({ date: '2026-10-20', condition: 'fix security issue' })
  })

  it('trims whitespace from condition', () => {
    const comment = { body: 'Revisit by: 2026-10-20 —   lots of   spaces  ' }
    expect(parseRevisitComment(comment)).toEqual({ date: '2026-10-20', condition: 'lots of   spaces' })
  })
})

describe('latestRevisit', () => {
  it('returns the newest comment when multiple exist', () => {
    const comments = [
      { body: 'Revisit by: 2026-10-10', createdAt: '2026-10-08T00:00:00Z' },
      { body: 'Revisit by: 2026-10-15', createdAt: '2026-10-09T00:00:00Z' }
    ]
    expect(latestRevisit(comments)).toEqual({ date: '2026-10-15', condition: null })
  })

  it('skips non-matching comments', () => {
    const comments = [
      { body: 'not a revisit', createdAt: '2026-10-09T00:00:00Z' },
      { body: 'Revisit by: 2026-10-15', createdAt: '2026-10-10T00:00:00Z' }
    ]
    expect(latestRevisit(comments)).toEqual({ date: '2026-10-15', condition: null })
  })

  it('returns null for empty array', () => {
    expect(latestRevisit([])).toBeNull()
  })

  it('returns null when all comments are malformed', () => {
    const comments = [
      { body: 'Revisit by: 2026-13-32', createdAt: '2026-10-10T00:00:00Z' },
      { body: 'let me revisit', createdAt: '2026-10-11T00:00:00Z' }
    ]
    expect(latestRevisit(comments)).toBeNull()
  })

  it('handles huge comment lists without slowdown', () => {
    const comments = Array.from({ length: 200 }, (_, i) => ({
      body: i === 199 ? 'Revisit by: 2026-10-25' : 'not revisit',
      createdAt: new Date(Date.UTC(2026, 9, i + 1)).toISOString()
    }))
    expect(latestRevisit(comments)).toEqual({ date: '2026-10-25', condition: null })
  })

  it('handles malformed createdAt and still finds valid comment', () => {
    const comments = [
      { body: 'Revisit by: 2026-10-10', createdAt: 'not-a-date' },
      { body: 'Revisit by: 2026-10-15', createdAt: '2026-10-09T00:00:00Z' }
    ]
    const result = latestRevisit(comments)
    expect(result).toEqual({ date: '2026-10-15', condition: null })
  })

  it('returns null for non-array input', () => {
    expect(latestRevisit(null)).toBeNull()
    expect(latestRevisit(undefined)).toBeNull()
  })

  it('handles condition extraction in latest comment', () => {
    const comments = [
      { body: 'Revisit by: 2026-10-10 — old condition', createdAt: '2026-10-08T00:00:00Z' },
      { body: 'Revisit by: 2026-10-15 — new condition', createdAt: '2026-10-09T00:00:00Z' }
    ]
    expect(latestRevisit(comments)).toEqual({ date: '2026-10-15', condition: 'new condition' })
  })
})
