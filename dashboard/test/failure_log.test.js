import { describe, it, expect, vi } from 'vitest'
import { recordFailure, recordFlaky } from '../webhook-server/failure_log.js'

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

describe('recordFlaky: a test that failed once then passed, kept apart from the breaker log', () => {
  it('appends one line to its own file, never the breaker log', () => {
    const append = vi.fn()
    const rec = recordFlaky({ tests: ['test/a.test.js'], prUrl: 'https://github.com/o/r/pull/1', project: 'o/r' },
      append, () => new Date('2026-10-30T10:00:00.000Z'), '/tmp/flaky.jsonl')
    expect(append).toHaveBeenCalledWith('/tmp/flaky.jsonl', expect.any(String))
    expect(JSON.parse(append.mock.calls[0][1])).toEqual({
      t: '2026-10-30T10:00:00.000Z', kind: 'flaky', tests: ['test/a.test.js'], pr_url: 'https://github.com/o/r/pull/1', project: 'o/r'
    })
    expect(rec.kind).toBe('flaky')
  })
  it('the default file is not pipeline-failures.jsonl', () => {
    const append = vi.fn()
    recordFlaky({ tests: ['x'] }, append)
    expect(append.mock.calls[0][0]).toMatch(/flaky-tests\.jsonl$/)
  })
  it('a write that throws never breaks the merge', () => {
    expect(recordFlaky({ tests: ['x'] }, () => { throw new Error('disk full') })).toBeNull()
  })
  it('caps what it stores (a huge or hostile name list)', () => {
    const append = vi.fn()
    recordFlaky({ tests: Array.from({ length: 50 }, () => 'x'.repeat(5000)) }, append)
    const r = JSON.parse(append.mock.calls[0][1])
    expect(r.tests.length).toBeLessThanOrEqual(15)
    expect(r.tests.every((t) => t.length <= 300)).toBe(true)
  })
})
