import { describe, it, expect } from 'vitest'
import { openLink, windowOpenHandler } from '../electron/main/external_links.js'

// A fake execFile: answers each call from a queue of errors and records what was asked.
function fakeRun(errors = []) {
  const calls = []
  const run = (cmd, args, opts, cb) => {
    calls.push({ cmd, args })
    cb(errors.shift() || null, '', '')
  }
  return { run, calls }
}
function fakeExternal() {
  const opened = []
  return { openExternal: async (u) => { opened.push(u) }, opened }
}
const PR = 'https://github.com/G-Eskayo/marvin/pull/657'

describe('Links clicked in the dashboard open in the browser you are signed in to', () => {
  it('opens a web link in Google Chrome when it is installed', async () => {
    const { run, calls } = fakeRun()
    const { openExternal, opened } = fakeExternal()
    expect(await openLink(PR, { run, appExists: () => true, openExternal })).toEqual({ ok: true, via: 'chrome' })
    expect(calls).toEqual([{ cmd: 'open', args: ['-a', 'Google Chrome', PR] }])
    expect(opened).toEqual([])
  })

  it('falls back to the default browser when Chrome is not installed', async () => {
    const { run, calls } = fakeRun()
    const { openExternal, opened } = fakeExternal()
    expect(await openLink(PR, { run, appExists: () => false, openExternal })).toEqual({ ok: true, via: 'default' })
    expect(calls).toEqual([])
    expect(opened).toEqual([PR])
  })

  it('falls back to the default browser when Chrome fails to open it', async () => {
    const { run } = fakeRun([new Error('LSOpenURLsWithRole() failed')])
    const { openExternal, opened } = fakeExternal()
    expect(await openLink(PR, { run, appExists: () => true, openExternal })).toEqual({ ok: true, via: 'default' })
    expect(opened).toEqual([PR])
  })

  it('sends mail links to the mail app, not Chrome', async () => {
    const { run, calls } = fakeRun()
    const { openExternal, opened } = fakeExternal()
    await openLink('mailto:a@example.com', { run, appExists: () => true, openExternal })
    expect(calls).toEqual([])
    expect(opened).toEqual(['mailto:a@example.com'])
  })

  it.each(['file:///etc/passwd', 'javascript:alert(1)', 'x-apple-script://run', '', null, '-a Calculator'])(
    'never opens %j anywhere', async (bad) => {
      const { run, calls } = fakeRun()
      const { openExternal, opened } = fakeExternal()
      expect((await openLink(bad, { run, appExists: () => true, openExternal })).ok).toBe(false)
      expect(calls).toEqual([])
      expect(opened).toEqual([])
    })
})

describe('A link that would open a new window', () => {
  it('never opens an Electron window (it would have no sign-in and the dashboard\'s own powers)', () => {
    const asked = []
    const handler = windowOpenHandler((u) => { asked.push(u) })
    expect(handler({ url: PR })).toEqual({ action: 'deny' })
    expect(asked).toEqual([PR])
  })

  it('still denies the window when opening the link throws', () => {
    const handler = windowOpenHandler(() => { throw new Error('boom') })
    expect(handler({ url: PR })).toEqual({ action: 'deny' })
  })
})
