import { describe, it, expect, vi } from 'vitest'
import { EventEmitter } from 'events'
import { createMockupWindows, installMockupSession, MOCKUP_PARTITION } from '../electron/main/mockup_window.js'
import { GONE } from '../electron/main/mockups.js'

// G-Eskayo/marvin#938: the mock-up window's sandbox and its protocol, with Electron faked (the rules are what matter).

function fakeSession() {
  const ses = new EventEmitter()
  ses.webRequest = { onBeforeRequest: vi.fn((fn) => { ses.filter = fn }) }
  ses.protocol = { handle: vi.fn((scheme, fn) => { ses.scheme = scheme; ses.handler = fn }) }
  ses.setPermissionRequestHandler = vi.fn((fn) => { ses.permission = fn })
  ses.setPermissionCheckHandler = vi.fn((fn) => { ses.permissionCheck = fn })
  return ses
}

function fakeElectron() {
  const sessions = {}
  const windows = []
  class BrowserWindow extends EventEmitter {
    constructor(opts) {
      super()
      this.opts = opts
      this.webContents = new EventEmitter()
      this.webContents.setWindowOpenHandler = (fn) => { this.openHandler = fn }
      this.loadURL = vi.fn(async (u) => { this.url = u })
      this.focus = vi.fn()
      this.show = vi.fn()
      this.isDestroyed = () => false
      windows.push(this)
    }
  }
  const session = { fromPartition: vi.fn((p) => (sessions[p] ||= fakeSession())) }
  return { BrowserWindow, session, sessions, windows }
}

const filterSays = (ses, url) => new Promise((resolve) => ses.filter({ url }, (r) => resolve(r)))
const okSource = (files) => ({
  read: vi.fn(async (_t, file) => (file in files ? { ok: true, body: Buffer.from(files[file]), mime: file.endsWith('.js') ? 'text/javascript' : 'text/html' } : { ok: false, gone: 'file', reason: GONE.file }))
})
const FILES = { 'docs/design/m/index.html': '<script src="answer_state.js"></script>', 'docs/design/m/answer_state.js': 'x=1', 'docs/design/README.md': 'secret' }
const ARGS = { repo: 'G-Eskayo/marvin', number: 934, sha: 'a990349dbd151f99eb4e17b84b150935aa673bb3', ref: 'design/924', path: 'docs/design/m/index.html' }

describe('installMockupSession: the network block', () => {
  it('cancels every request that is not marvin-mockup://', async () => {
    const ses = fakeSession()
    installMockupSession(ses, () => {})
    expect((await filterSays(ses, 'marvin-mockup://id/index.html')).cancel).toBe(false)
    for (const u of ['https://api.github.com/user', 'http://localhost:5173/', 'wss://x/', 'file:///Users/x/.claude/.gh-token', 'prmedia://media/abc']) {
      expect((await filterSays(ses, u)).cancel, u).toBe(true)
    }
  })
  it('denies every permission and cancels downloads', () => {
    const ses = fakeSession()
    installMockupSession(ses, () => {})
    const cb = vi.fn()
    ses.permission(null, 'media', cb)
    expect(cb).toHaveBeenCalledWith(false)
    expect(ses.permissionCheck()).toBe(false)
    const item = { cancel: vi.fn() }
    const ev = { preventDefault: vi.fn() }
    ses.emit('will-download', ev, item)
    expect(ev.preventDefault).toHaveBeenCalled()
    expect(item.cancel).toHaveBeenCalled()
  })
})

describe('createMockupWindows: opening a mock-up', () => {
  it('opens a sandboxed window on its own partition, with no preload, Node or window.api, titled like the app', async () => {
    const e = fakeElectron()
    const mw = createMockupWindows({ ...e, source: okSource(FILES), newId: () => 'abc123' })
    expect(await mw.open(ARGS)).toEqual({ ok: true })
    const [win] = e.windows
    const wp = win.opts.webPreferences
    expect(wp.partition).toBe(MOCKUP_PARTITION)
    expect(wp.partition.startsWith('persist:')).toBe(false)
    expect(wp.sandbox).toBe(true)
    expect(wp.contextIsolation).toBe(true)
    expect(wp.nodeIntegration).toBe(false)
    expect(wp.webviewTag).toBe(false)
    expect(wp.preload).toBeUndefined()
    expect(win.opts.title).toBe('MARVIN · Mock-up: m (#934)')
    expect(win.url).toBe('marvin-mockup://abc123/index.html')
    expect(e.session.fromPartition).toHaveBeenCalledWith(MOCKUP_PARTITION)
    expect(e.sessions[MOCKUP_PARTITION].scheme).toBe('marvin-mockup')
  })
  it('keeps MARVIN\'s title when the page sets its own', async () => {
    const e = fakeElectron()
    await createMockupWindows({ ...e, source: okSource(FILES) }).open(ARGS)
    const ev = { preventDefault: vi.fn() }
    e.windows[0].emit('page-title-updated', ev, 'Prototype')
    expect(ev.preventDefault).toHaveBeenCalled()
  })
  it('denies window.open and every navigation away from the mock-up', async () => {
    const e = fakeElectron()
    await createMockupWindows({ ...e, source: okSource(FILES), newId: () => 'abc123' }).open(ARGS)
    const win = e.windows[0]
    expect(win.openHandler({ url: 'https://evil.example' })).toEqual({ action: 'deny' })
    expect(win.openHandler({ url: 'marvin-mockup://abc123/other.html' })).toEqual({ action: 'deny' })
    for (const [event, url, blocked] of [
      ['will-navigate', 'https://evil.example', true],
      ['will-navigate', 'marvin-mockup://otherid/index.html', true],
      ['will-navigate', 'file:///etc/passwd', true],
      ['will-redirect', 'https://evil.example', true],
      ['will-navigate', 'marvin-mockup://abc123/index.html#b', false]
    ]) {
      const ev = { preventDefault: vi.fn() }
      win.webContents.emit(event, ev, url)
      expect(ev.preventDefault.mock.calls.length > 0, `${event} ${url}`).toBe(blocked)
    }
    const att = { preventDefault: vi.fn() }
    win.webContents.emit('will-attach-webview', att)
    expect(att.preventDefault).toHaveBeenCalled()
  })
  it('a second open of the same mock-up focuses the window instead of opening another', async () => {
    const e = fakeElectron()
    const mw = createMockupWindows({ ...e, source: okSource(FILES) })
    await mw.open(ARGS)
    expect(await mw.open(ARGS)).toEqual({ ok: true, reused: true })
    expect(e.windows).toHaveLength(1)
    expect(e.windows[0].focus).toHaveBeenCalled()
    e.windows[0].emit('closed')
    await mw.open(ARGS)
    expect(e.windows).toHaveLength(2)
  })
  it('a deleted branch or a missing page opens nothing and hands back the plain message', async () => {
    const e = fakeElectron()
    const gone = { read: vi.fn(async () => ({ ok: false, gone: 'branch', reason: GONE.branch })) }
    expect(await createMockupWindows({ ...e, source: gone }).open(ARGS)).toEqual({ ok: false, gone: 'branch', reason: 'This mock-up is gone: its branch was deleted' })
    expect(await createMockupWindows({ ...e, source: okSource({}) }).open(ARGS)).toMatchObject({ ok: false, gone: 'file' })
    expect(e.windows).toHaveLength(0)
  })
  it('refuses a page path that isn\'t a page, or climbs out', async () => {
    const e = fakeElectron()
    const source = okSource(FILES)
    const mw = createMockupWindows({ ...e, source })
    for (const p of ['../x/index.html', '/etc/index.html', 'docs/design/m/answer_state.js', '', undefined]) {
      expect((await mw.open({ ...ARGS, path: p })).ok, String(p)).toBe(false)
    }
    expect(source.read).not.toHaveBeenCalled()
    expect(e.windows).toHaveLength(0)
  })
})

describe('the marvin-mockup:// protocol', () => {
  async function opened() {
    const e = fakeElectron()
    const source = okSource(FILES)
    const mw = createMockupWindows({ ...e, source, newId: () => 'abc123' })
    await mw.open(ARGS)
    const handler = e.sessions[MOCKUP_PARTITION].handler
    return { handler, source, e, mw }
  }
  it('serves the page and its relative script from the PR\'s head commit, with the CSP', async () => {
    const { handler, source } = await opened()
    const page = await handler({ url: 'marvin-mockup://abc123/index.html' })
    expect(page.status).toBe(200)
    expect(page.headers.get('content-security-policy')).toContain('connect-src marvin-mockup:')
    const js = await handler({ url: 'marvin-mockup://abc123/answer_state.js?v=2' })
    expect(await js.text()).toBe('x=1')
    expect(js.headers.get('content-type')).toBe('text/javascript')
    expect(source.read).toHaveBeenLastCalledWith({ repo: 'G-Eskayo/marvin', sha: ARGS.sha, ref: 'design/924', number: 934 }, 'docs/design/m/answer_state.js')
  })
  it('refuses anything outside the mock-up\'s folder, however it is spelled', async () => {
    const { handler, source } = await opened()
    source.read.mockClear()
    for (const p of ['/../README.md', '/%2e%2e/README.md', '/%2E%2E%2FREADME.md', '/..%2f..%2f..%2fREADME.md', '/%252e%252e/README.md', '/a%5c..%5c..%5cREADME.md']) {
      const r = await handler({ url: `marvin-mockup://abc123${p}` })
      expect(r.status, p).toBe(403)
    }
    expect(source.read).not.toHaveBeenCalled()
  })
  it('an unknown window id, a missing file and a bad address are plain 4xx answers', async () => {
    const { handler } = await opened()
    expect((await handler({ url: 'marvin-mockup://nope/index.html' })).status).toBe(404)
    expect((await handler({ url: 'marvin-mockup://abc123/missing.js' })).status).toBe(404)
    expect((await handler({ url: '::::' })).status).toBe(400)
  })
  it('stops serving once its window closes', async () => {
    const { handler, e } = await opened()
    e.windows[0].emit('closed')
    expect((await handler({ url: 'marvin-mockup://abc123/index.html' })).status).toBe(404)
  })
})
