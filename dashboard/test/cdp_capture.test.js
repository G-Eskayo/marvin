import { describe, it, expect, vi } from 'vitest'
import { EventEmitter } from 'node:events'
import net from 'node:net'
import { captureViaCdp, freePort } from '../src/lib/cdp_capture.js'

// marvin#421: Playwright's chromium.launch rejects Electron's app-dir argument ("Arguments can not specify page to be
// opened"), so UI PRs had no screenshots and were refused. Capture now launches Electron itself and attaches over CDP.

function fakeProc() {
  const p = new EventEmitter()
  p.exitCode = null
  p.kills = []
  p.kill = (sig) => { p.kills.push(sig); if (sig === 'SIGKILL' || p.dieOnTerm) { p.exitCode = 0; p.emit('exit', 0) } return true }
  return p
}

function deps({ connectFailures = 0, pages = [() => ({ url: () => 'file:///app/index.html' })], screenshotThrows = false, exitAt = null } = {}) {
  const proc = fakeProc()
  proc.dieOnTerm = true
  const shots = []
  let attempts = 0
  const page = {
    url: () => 'file:///app/index.html',
    waitForLoadState: vi.fn(async () => {}),
    setViewportSize: vi.fn(async () => {}),
    screenshot: vi.fn(async ({ path }) => { if (screenshotThrows) throw new Error('screenshot failed'); shots.push(path) })
  }
  const browser = { contexts: () => [{ pages: () => pages.map((f) => (f ? { ...f(), ...page, url: f().url } : null)).filter(Boolean) }], close: vi.fn(async () => {}) }
  const chromium = {
    connectOverCDP: vi.fn(async () => {
      attempts++
      if (exitAt !== null && attempts === exitAt) { proc.exitCode = 1; proc.emit('exit', 1) }
      if (attempts <= connectFailures) throw new Error('ECONNREFUSED')
      return browser
    })
  }
  const spawn = vi.fn(() => proc)
  return { proc, shots, browser, chromium, spawn, page }
}

const base = { electronBin: '/e', appDir: '/app', env: {}, outputPath: '/out/shot.png', pollMs: 1, findPort: async () => 9555 }

describe('captureViaCdp', () => {
  it('launches Electron with a debugging port, attaches, screenshots the app window, and cleans up', async () => {
    const d = deps({ connectFailures: 2 })
    const r = await captureViaCdp({ ...base, chromium: d.chromium, spawn: d.spawn })
    expect(r).toEqual({ ok: true, path: '/out/shot.png' })
    expect(d.spawn.mock.calls[0][1]).toEqual(['/app', '--no-sandbox', '--remote-debugging-port=9555'])
    expect(d.shots).toEqual(['/out/shot.png'])
    expect(d.browser.close).toHaveBeenCalled()
    expect(d.proc.kills[0]).toBe('SIGTERM')
  })

  it('never passes the app dir to chromium.launch (the broken path)', async () => {
    const d = deps()
    d.chromium.launch = vi.fn()
    await captureViaCdp({ ...base, chromium: d.chromium, spawn: d.spawn })
    expect(d.chromium.launch).not.toHaveBeenCalled()
  })

  it('Electron exiting immediately is a clear error, not a hang', async () => {
    const d = deps({ connectFailures: 999, exitAt: 1 })
    const r = await captureViaCdp({ ...base, chromium: d.chromium, spawn: d.spawn, attachTimeoutMs: 2000 })
    expect(r.ok).toBe(false)
    expect(r.error).toMatch(/Electron exited \(code 1\) before the window opened/)
  })

  it('never attaching is a clear error within the timeout', async () => {
    const d = deps({ connectFailures: 999 })
    d.proc.dieOnTerm = false
    const r = await captureViaCdp({ ...base, chromium: d.chromium, spawn: d.spawn, attachTimeoutMs: 30 })
    expect(r).toMatchObject({ ok: false })
    expect(r.error).toMatch(/could not attach/)
    expect(d.proc.kills).toEqual(['SIGTERM', 'SIGKILL']) // still cleaned up, forcefully when TERM is ignored
  })

  it('no content window is a clear error, and still cleans up', async () => {
    const d = deps({ pages: [() => ({ url: () => 'devtools://x' })] })
    const r = await captureViaCdp({ ...base, chromium: d.chromium, spawn: d.spawn, windowTimeoutMs: 20 })
    expect(r.error).toMatch(/no app window/)
    expect(d.browser.close).toHaveBeenCalled()
    expect(d.proc.kills.length).toBeGreaterThan(0)
  })

  it('a failing screenshot is reported with its reason and cleans up', async () => {
    const d = deps({ screenshotThrows: true })
    const r = await captureViaCdp({ ...base, chromium: d.chromium, spawn: d.spawn })
    expect(r).toEqual({ ok: false, error: 'screenshot failed' })
    expect(d.proc.kills.length).toBeGreaterThan(0)
  })

  it('spawn throwing (no Electron binary) is a clear error', async () => {
    const r = await captureViaCdp({ ...base, chromium: { connectOverCDP: vi.fn() }, spawn: () => { throw new Error('ENOENT') } })
    expect(r).toEqual({ ok: false, error: 'could not start Electron: ENOENT' })
  })
})

describe('freePort', () => {
  it('returns a port nothing is listening on, even when a common one is taken', async () => {
    const busy = net.createServer().listen(0)
    await new Promise((r) => busy.once('listening', r))
    const p = await freePort()
    expect(p).toBeGreaterThan(0)
    expect(p).not.toBe(busy.address().port)
    const probe = net.createServer().listen(p)
    await new Promise((res, rej) => { probe.once('listening', res); probe.once('error', rej) })
    probe.close()
    busy.close()
  })
})
