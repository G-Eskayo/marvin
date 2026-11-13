import { describe, it, expect, vi } from 'vitest'
import { EventEmitter } from 'node:events'
import { isEvidenceCapture, installCaptureGuard } from '../electron/main/capture_mode.js'

describe('isEvidenceCapture', () => {
  it('is true only for MARVIN_EVIDENCE_CAPTURE=1', () => {
    expect(isEvidenceCapture({ MARVIN_EVIDENCE_CAPTURE: '1' })).toBe(true)
    expect(isEvidenceCapture({ MARVIN_EVIDENCE_CAPTURE: ' 1 ' })).toBe(true)
  })

  it('is false when unset, empty, 0, or anything else', () => {
    for (const v of [undefined, '', '0', 'true', 'yes', '2']) {
      expect(isEvidenceCapture({ MARVIN_EVIDENCE_CAPTURE: v }), String(v)).toBe(false)
    }
    expect(isEvidenceCapture({})).toBe(false)
    expect(isEvidenceCapture(undefined)).toBe(false)
  })
})

describe('installCaptureGuard', () => {
  it('logs uncaught exceptions and unhandled rejections instead of letting them surface', () => {
    const proc = new EventEmitter()
    const log = vi.fn()
    installCaptureGuard(proc, log)

    expect(() => proc.emit('uncaughtException', new Error('EADDRINUSE something'))).not.toThrow()
    expect(() => proc.emit('unhandledRejection', new Error('nope'))).not.toThrow()
    expect(log).toHaveBeenCalledTimes(2)
    expect(log.mock.calls[0][0]).toMatch(/evidence capture.*uncaught.*EADDRINUSE something/)
    expect(log.mock.calls[1][0]).toMatch(/evidence capture.*unhandled rejection.*nope/)
  })

  it('handles non-Error throwables', () => {
    const proc = new EventEmitter()
    const log = vi.fn()
    installCaptureGuard(proc, log)
    expect(() => proc.emit('uncaughtException', 'a string')).not.toThrow()
    expect(() => proc.emit('unhandledRejection', undefined)).not.toThrow()
    expect(log).toHaveBeenCalledTimes(2)
  })

  it('a throwing logger cannot re-raise from inside the guard', () => {
    const proc = new EventEmitter()
    installCaptureGuard(proc, () => { throw new Error('stderr gone') })
    expect(() => proc.emit('uncaughtException', new Error('x'))).not.toThrow()
  })
})

// marvin#873: the Vitals mock-up's captures read the worktree's map and a saved accounts sweep. Only in capture mode,
// only absolute paths; Gil's own dashboard ignores the variables completely.
import { captureOverride } from '../electron/main/capture_mode.js'
describe('captureOverride', () => {
  it('only in evidence-capture mode, only an absolute path', () => {
    expect(captureOverride({ MARVIN_EVIDENCE_CAPTURE: '1', MARVIN_CAPTURE_MAP_DIR: '/x/brain-map' }, 'MARVIN_CAPTURE_MAP_DIR')).toBe('/x/brain-map')
    expect(captureOverride({ MARVIN_CAPTURE_MAP_DIR: '/x/brain-map' }, 'MARVIN_CAPTURE_MAP_DIR')).toBe(null)
    expect(captureOverride({ MARVIN_EVIDENCE_CAPTURE: '0', MARVIN_CAPTURE_MAP_DIR: '/x' }, 'MARVIN_CAPTURE_MAP_DIR')).toBe(null)
    expect(captureOverride({ MARVIN_EVIDENCE_CAPTURE: '1', MARVIN_CAPTURE_MAP_DIR: 'relative/dir' }, 'MARVIN_CAPTURE_MAP_DIR')).toBe(null)
    expect(captureOverride({ MARVIN_EVIDENCE_CAPTURE: '1', MARVIN_CAPTURE_MAP_DIR: '' }, 'MARVIN_CAPTURE_MAP_DIR')).toBe(null)
    expect(captureOverride({ MARVIN_EVIDENCE_CAPTURE: '1', MARVIN_CAPTURE_MAP_DIR: '/a/../../etc' }, 'MARVIN_CAPTURE_MAP_DIR')).toBe('/etc')
    expect(captureOverride(null, 'X')).toBe(null)
  })
})
