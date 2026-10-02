import { describe, it, expect, vi } from 'vitest'
import { recordFailure } from '../webhook-server/failure_log.js'

describe('recordFailure', () => {
  it('appends one JSON line in the shape lib/failure_breaker.py reads', () => {
    const append = vi.fn()
    const rec = recordFailure(
      { ticket: 32, code: 'GH_AUTH_INVALID', message: 'Bad credentials' },
      append,
      () => new Date('2026-10-02T14:00:00.000Z'),
      '/tmp/x.jsonl'
    )
    expect(append).toHaveBeenCalledTimes(1)
    const [file, line] = append.mock.calls[0]
    expect(file).toBe('/tmp/x.jsonl')
    expect(line.endsWith('\n')).toBe(true)
    expect(JSON.parse(line)).toEqual({
      t: '2026-10-02T14:00:00.000Z',
      kind: 'failure',
      ticket: 32,
      sig: 'merge:GH_AUTH_INVALID',
      reason: 'GH_AUTH_INVALID: Bad credentials'
    })
    expect(rec.sig).toBe('merge:GH_AUTH_INVALID')
  })

  it('never throws, even when the write fails', () => {
    const append = vi.fn(() => { throw new Error('disk full') })
    expect(() => recordFailure({ ticket: 1, code: 'X', message: 'm' }, append)).not.toThrow()
    expect(recordFailure({ ticket: 1, code: 'X', message: 'm' }, append)).toBeNull()
  })

  it('caps an enormous message', () => {
    const append = vi.fn()
    recordFailure({ ticket: 1, code: 'X', message: 'm'.repeat(5000) }, append, () => new Date(), '/tmp/x')
    expect(JSON.parse(append.mock.calls[0][1]).reason.length).toBeLessThanOrEqual(300)
  })
})
