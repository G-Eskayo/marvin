import { describe, it, expect } from 'vitest'
import { MESSAGE_FADE_MS, messageExpired } from '../src/lib/fade_message.js'

describe('fade_message', () => {
  // Tests 14-15: MESSAGE_FADE_MS constant and messageExpired function
  it('exports MESSAGE_FADE_MS as 4000', () => {
    expect(MESSAGE_FADE_MS).toBe(4000)
  })

  it('messageExpired returns false when elapsed time is less than MESSAGE_FADE_MS', () => {
    const setAt = new Date('2026-11-15T12:00:00Z')
    const now = new Date('2026-11-15T12:00:03Z') // 3 seconds later
    expect(messageExpired(setAt, now)).toBe(false)
  })

  it('messageExpired returns true when elapsed time equals MESSAGE_FADE_MS', () => {
    const setAt = new Date('2026-11-15T12:00:00Z')
    const now = new Date('2026-11-15T12:00:04Z') // exactly 4 seconds later
    expect(messageExpired(setAt, now)).toBe(true)
  })

  it('messageExpired returns true when elapsed time exceeds MESSAGE_FADE_MS', () => {
    const setAt = new Date('2026-11-15T12:00:00Z')
    const now = new Date('2026-11-15T12:00:05Z') // 5 seconds later
    expect(messageExpired(setAt, now)).toBe(true)
  })

  it('messageExpired works with timestamp numbers (Date.now() format)', () => {
    const base = new Date('2026-11-15T12:00:00Z').getTime()
    const setAt = base
    const nowBeforeFade = base + 3000 // 3 seconds later
    const nowAfterFade = base + 4000 // exactly 4 seconds later
    const nowWayAfter = base + 5000 // 5 seconds later
    expect(messageExpired(setAt, nowBeforeFade)).toBe(false)
    expect(messageExpired(setAt, nowAfterFade)).toBe(true)
    expect(messageExpired(setAt, nowWayAfter)).toBe(true)
  })

  it('messageExpired returns false when setAt is null', () => {
    const now = new Date('2026-11-15T12:00:00Z')
    expect(messageExpired(null, now)).toBe(false)
  })

  it('messageExpired handles mixed Date and timestamp types', () => {
    const dateSetAt = new Date('2026-11-15T12:00:00Z')
    const nowTimestamp = dateSetAt.getTime() + 4000
    expect(messageExpired(dateSetAt, nowTimestamp)).toBe(true)
  })
})
