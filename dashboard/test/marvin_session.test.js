import { describe, it, expect } from 'vitest'
import { sessionArgs, openMarvinSession } from '../electron/main/marvin_session.js'

describe('MARVIN button session launcher', () => {
  it('asks for a ticket worktree when given a number, with or without #', () => {
    expect(sessionArgs({ ticket: '#228' }).slice(1)).toEqual(['open', '--ticket', '228'])
    expect(sessionArgs({ ticket: 291, repo: 'G-Eskayo/marvin' }).slice(1)).toEqual(['open', '--ticket', '291', '--repo', 'G-Eskayo/marvin'])
  })

  it('opens a no-ticket session when the box is empty', () => {
    expect(sessionArgs({ ticket: '' }).slice(1)).toEqual(['open'])
  })

  it('refuses something that is not a ticket number without running anything', async () => {
    let ran = false
    const result = await openMarvinSession({ ticket: 'abc' }, { run: () => { ran = true } })
    expect(result.ok).toBe(false)
    expect(ran).toBe(false)
  })

  it('reports what the launcher said, and a clear error when it said nothing', async () => {
    const ok = await openMarvinSession({}, { run: (_c, _a, _o, cb) => cb(null, '{"ok": true, "dir": "/Users/x"}\n', '') })
    expect(ok).toEqual({ ok: true, dir: '/Users/x' })
    const bad = await openMarvinSession({}, { run: (_c, _a, _o, cb) => cb(new Error('boom'), '', 'Traceback...') })
    expect(bad).toEqual({ ok: false, error: 'Traceback...' })
  })
})
