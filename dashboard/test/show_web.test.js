// A web address shown by `marvin show` renders in the window (#715, owner's answer on PR #1029), in an isolated view,
// with the link card as the fallback. Electron's WebContentsView faked; the rules are the real ones.
import { describe, it, expect, vi } from 'vitest'
import { EventEmitter } from 'events'
import { webRequestOk, isLocalHost, isWebAddress, installWebSession, clampViewBounds, createWebPane, SHOW_WEB_PARTITION } from '../electron/main/show_web.js'

function fakeView() {
  const views = []
  class WebContentsView {
    constructor(opts) {
      this.opts = opts
      this.webContents = new EventEmitter()
      this.webContents.loadURL = vi.fn(() => Promise.resolve())
      this.webContents.close = vi.fn()
      this.webContents.setWindowOpenHandler = (fn) => { this.openHandler = fn }
      this.setBounds = vi.fn()
      views.push(this)
    }
  }
  return { WebContentsView, views }
}
function fakeWin() {
  const children = new Set()
  return {
    children,
    destroyed: false,
    isDestroyed() { return this.destroyed },
    getContentBounds: () => ({ x: 0, y: 0, width: 900, height: 700 }),
    contentView: { addChildView: vi.fn((v) => children.add(v)), removeChildView: vi.fn((v) => children.delete(v)) }
  }
}
const pane = (url = 'https://example.com/a', extra = {}) => {
  const { WebContentsView, views } = fakeView()
  const win = fakeWin()
  const states = []
  const p = createWebPane({ WebContentsView, win, url, onState: (s) => states.push(s), ...extra })
  return { p, view: views[0], win, states }
}

describe('what a shown page may reach', () => {
  it('web pages, their data: and blob: parts, and websockets', () => {
    for (const u of ['https://example.com/', 'http://example.com/x', 'wss://example.com/s', 'data:image/png;base64,AA', 'blob:https://example.com/1']) expect(webRequestOk(u)).toBe(true)
  })
  it('never the app\'s own files, schemes or this Mac\'s files', () => {
    for (const u of ['file:///etc/passwd', 'marvin-mockup://f1/index.html', 'prmedia://x', 'chrome://settings', 'javascript:alert(1)', 'ftp://example.com/', 'not a url']) expect(webRequestOk(u)).toBe(false)
  })
  it('never this Mac or the local network (the refresh server on 127.0.0.1:7879, the router), in any spelling', () => {
    for (const u of ['http://127.0.0.1:7879/show', 'http://localhost:7879/', 'http://LOCALHOST./', 'http://[::1]/', 'http://[::ffff:127.0.0.1]/', 'http://2130706433/', 'http://0x7f000001/', 'http://0.0.0.0/', 'http://192.168.1.1/', 'http://10.0.0.2/', 'http://172.20.0.1/', 'http://169.254.169.254/latest', 'http://100.101.102.103/', 'http://gils-mac-mini.local/', 'http://[fd00::1]/', 'http://[fe80::1]/']) {
      expect(webRequestOk(u), u).toBe(false)
    }
    expect(webRequestOk('http://172.32.0.1/')).toBe(true) // just outside 172.16/12
    expect(isLocalHost('example.com')).toBe(false)
  })
  it('a local address Gil asked to show is allowed: that host and port only', () => {
    const hosts = new Set(['localhost:5173'])
    expect(webRequestOk('http://localhost:5173/src/main.jsx', hosts)).toBe(true)
    expect(webRequestOk('ws://localhost:5173/', hosts)).toBe(true)
    expect(webRequestOk('http://localhost:7879/show', hosts)).toBe(false)
    expect(webRequestOk('http://127.0.0.1:5173/', hosts)).toBe(false)
  })
  it('the session refuses everything else, every permission and every download', () => {
    const ses = new EventEmitter()
    ses.webRequest = { onBeforeRequest: (fn) => { ses.filter = fn } }
    ses.setPermissionRequestHandler = (fn) => { ses.permission = fn }
    ses.setPermissionCheckHandler = (fn) => { ses.check = fn }
    installWebSession(ses, new Set())
    const cb = vi.fn()
    ses.filter({ url: 'http://127.0.0.1:7879/show' }, cb)
    ses.filter({ url: 'https://example.com/' }, cb)
    expect(cb.mock.calls).toEqual([[{ cancel: true }], [{ cancel: false }]])
    const allow = vi.fn()
    ses.permission(null, 'media', allow)
    expect(allow).toHaveBeenCalledWith(false)
    expect(ses.check()).toBe(false)
    const item = { cancel: vi.fn() }
    const ev = { preventDefault: vi.fn() }
    ses.emit('will-download', ev, item)
    expect(ev.preventDefault).toHaveBeenCalled()
    expect(item.cancel).toHaveBeenCalled()
  })
})

describe('clampViewBounds', () => {
  it('keeps the view inside the window, whatever the page sends', () => {
    expect(clampViewBounds({ x: 0, y: 49, width: 900, height: 651 }, { width: 900, height: 700 })).toEqual({ x: 0, y: 49, width: 900, height: 651 })
    expect(clampViewBounds({ x: -50, y: 49.6, width: 5000, height: 5000 }, { width: 900, height: 700 })).toEqual({ x: 0, y: 50, width: 900, height: 650 })
    expect(clampViewBounds({ x: 'a', y: NaN, width: null }, { width: 900, height: 700 })).toEqual({ x: 0, y: 0, width: 0, height: 0 })
    expect(clampViewBounds(null, null)).toEqual({ x: 0, y: 0, width: 0, height: 0 })
  })
})

describe('createWebPane', () => {
  it('loads the page in an isolated view: own in-memory session, sandboxed, no Node, no preload', () => {
    const { view, states } = pane()
    expect(view.webContents.loadURL).toHaveBeenCalledWith('https://example.com/a')
    const wp = view.opts.webPreferences
    expect(wp).toMatchObject({ partition: SHOW_WEB_PARTITION, sandbox: true, contextIsolation: true, nodeIntegration: false, webviewTag: false })
    expect(wp.preload).toBeUndefined()
    expect(SHOW_WEB_PARTITION.startsWith('persist:')).toBe(false)
    expect(states).toEqual([{ state: 'loading', url: 'https://example.com/a' }])
  })

  it('the view is laid over the window only once the page has something to draw, at the reserved box', () => {
    const { p, view, win, states } = pane()
    p.setBounds({ x: 0, y: 49, width: 900, height: 651 })
    expect(win.contentView.addChildView).not.toHaveBeenCalled()
    view.webContents.emit('dom-ready')
    expect(win.children.has(view)).toBe(true)
    expect(view.setBounds).toHaveBeenLastCalledWith({ x: 0, y: 49, width: 900, height: 651 })
    expect(states.at(-1)).toEqual({ state: 'loaded', url: 'https://example.com/a' })
    p.setBounds({ x: 0, y: 49, width: 600, height: 400 })
    expect(view.setBounds).toHaveBeenLastCalledWith({ x: 0, y: 49, width: 600, height: 400 })
  })

  it('a page that can\'t load falls back to the link card, with the reason (no connection, a refused address)', () => {
    const { view, win, states } = pane()
    view.webContents.emit('did-fail-load', {}, -106, 'ERR_INTERNET_DISCONNECTED', 'https://example.com/a', true)
    expect(states.at(-1)).toMatchObject({ state: 'failed', url: 'https://example.com/a' })
    expect(states.at(-1).reason).toMatch(/ERR_INTERNET_DISCONNECTED/)
    expect(win.children.size).toBe(0)
  })

  it('found live: Chromium sends dom-ready for its error page after did-fail-load; the card stays', () => {
    // the real order for https://does-not-exist.invalid/ in Electron 30 (probed 2026-11-03)
    const { view, win, states } = pane('https://does-not-exist.invalid/')
    const wc = view.webContents
    wc.emit('did-start-loading')
    wc.emit('did-start-navigation', {}, 'https://does-not-exist.invalid/', false, true)
    wc.emit('did-fail-load', {}, -105, 'ERR_NAME_NOT_RESOLVED', 'https://does-not-exist.invalid/', true)
    wc.emit('dom-ready')
    wc.emit('did-finish-load')
    wc.emit('did-stop-loading')
    expect(win.children.size).toBe(0)
    expect(states.at(-1)).toMatchObject({ state: 'failed' })
    // a new main-frame navigation (a link the window opened here) may draw again
    wc.emit('did-start-navigation', {}, 'https://example.com/', false, true)
    wc.emit('dom-ready')
    expect(win.children.has(view)).toBe(true)
    expect(states.at(-1).state).toBe('loaded')
  })

  it('a sub-frame or same-document navigation does not clear a failure', () => {
    const { view, win } = pane()
    const wc = view.webContents
    wc.emit('did-fail-load', {}, -106, 'x', 'https://example.com/a', true)
    wc.emit('did-start-navigation', {}, 'https://frame.example/', false, false)
    wc.emit('did-start-navigation', {}, 'https://example.com/a#x', true, true)
    wc.emit('dom-ready')
    expect(win.children.size).toBe(0)
  })

  it('found live: loadURL also rejects after did-fail-load; the specific reason is kept', async () => {
    let reject
    const { WebContentsView } = fakeView()
    class Late extends WebContentsView { constructor(o) { super(o); this.webContents.loadURL = vi.fn(() => new Promise((_r, j) => { reject = j })) } }
    const states = []
    const { views } = { views: [] }
    const p = createWebPane({ WebContentsView: Late, win: fakeWin(), url: 'https://does-not-exist.invalid/', onState: (s) => states.push(s) })
    p.view.webContents.emit('did-fail-load', {}, -105, 'ERR_NAME_NOT_RESOLVED', 'https://does-not-exist.invalid/', true)
    reject(new Error('ERR_NAME_NOT_RESOLVED'))
    await new Promise((r) => setTimeout(r, 0))
    expect(states.at(-1).reason).toMatch(/ERR_NAME_NOT_RESOLVED/)
    expect(states.filter((s) => s.state === 'failed')).toHaveLength(1)
    expect(views).toHaveLength(0)
  })

  it('a page that loaded and then crashed is taken off the window, and the card shows', () => {
    const { view, win, states } = pane()
    view.webContents.emit('dom-ready')
    view.webContents.emit('render-process-gone', {}, { reason: 'crashed' })
    expect(win.children.size).toBe(0)
    expect(states.at(-1)).toMatchObject({ state: 'failed', reason: 'The page stopped working in MARVIN' })
  })

  it('a failed sub-frame (an ad) or an aborted navigation is not a failure', () => {
    const { view, states } = pane()
    view.webContents.emit('dom-ready')
    view.webContents.emit('did-fail-load', {}, -20, 'ERR_BLOCKED_BY_CLIENT', 'https://ads.example/', false)
    view.webContents.emit('did-fail-load', {}, -3, 'ERR_ABORTED', 'https://example.com/b', true)
    expect(states.at(-1).state).toBe('loaded')
  })

  it('a load that rejects without saying why still falls back', async () => {
    const { WebContentsView, views } = fakeView()
    const orig = WebContentsView
    class Rejecting extends orig { constructor(o) { super(o); this.webContents.loadURL = vi.fn(() => Promise.reject(new Error('x'))) } }
    const states = []
    createWebPane({ WebContentsView: Rejecting, win: fakeWin(), url: 'https://example.com/', onState: (s) => states.push(s) })
    await new Promise((r) => setTimeout(r, 0))
    expect(states.at(-1).state).toBe('failed')
    expect(views).toHaveLength(1)
  })

  it('an address that isn\'t a web page is never loaded: the card says so', async () => {
    const { view, states } = pane('file:///etc/passwd')
    await Promise.resolve()
    expect(view.webContents.loadURL).not.toHaveBeenCalled()
    expect(states.at(-1)).toMatchObject({ state: 'failed', reason: 'Only web pages (http or https) open in MARVIN' })
  })

  it('links stay inside the view: no pop-ups, no other apps, no file: or javascript:', () => {
    const { view } = pane()
    expect(view.openHandler({ url: 'https://example.com/next' })).toEqual({ action: 'deny' })
    expect(view.webContents.loadURL).toHaveBeenLastCalledWith('https://example.com/next')
    expect(view.openHandler({ url: 'file:///etc/hosts' })).toEqual({ action: 'deny' })
    expect(view.webContents.loadURL).toHaveBeenCalledTimes(2)
    for (const to of ['file:///etc/hosts', 'zoommtg://join', 'javascript:alert(1)']) {
      const ev = { preventDefault: vi.fn(), url: to }
      view.webContents.emit('will-navigate', ev, to)
      expect(ev.preventDefault, to).toHaveBeenCalled()
    }
    const ok = { preventDefault: vi.fn() }
    view.webContents.emit('will-navigate', ok, 'https://example.com/c')
    expect(ok.preventDefault).not.toHaveBeenCalled()
    const wv = { preventDefault: vi.fn() }
    view.webContents.emit('will-attach-webview', wv)
    expect(wv.preventDefault).toHaveBeenCalled()
  })

  it('follows the page as Gil clicks around, so "Open in browser" opens where he is', () => {
    const { p, view, states } = pane()
    view.webContents.emit('dom-ready')
    view.webContents.emit('did-navigate', {}, 'https://example.com/b')
    expect(p.url).toBe('https://example.com/b')
    expect(states.at(-1)).toEqual({ state: 'loaded', url: 'https://example.com/b' })
    view.webContents.emit('did-navigate-in-page', {}, 'https://example.com/b#x', true)
    expect(states.at(-1).url).toBe('https://example.com/b#x')
    view.webContents.emit('did-navigate-in-page', {}, 'https://frame.example/', false)
    expect(p.url).toBe('https://example.com/b#x')
  })

  it('closed: off the window, its page closed, and silent after (twice is fine)', () => {
    const { p, view, win, states } = pane()
    view.webContents.emit('dom-ready')
    const n = states.length
    p.close()
    p.close()
    expect(win.children.size).toBe(0)
    expect(view.webContents.close).toHaveBeenCalledTimes(1)
    view.webContents.emit('did-fail-load', {}, -106, 'x', 'https://example.com/a', true)
    view.webContents.emit('dom-ready')
    expect(states).toHaveLength(n)
    expect(win.children.size).toBe(0)
  })

  it('a window already destroyed is never attached to', () => {
    const { view, win } = pane()
    win.destroyed = true
    view.webContents.emit('dom-ready')
    expect(win.contentView.addChildView).not.toHaveBeenCalled()
  })

  it('isWebAddress', () => {
    expect(isWebAddress('https://x.y/')).toBe(true)
    expect(isWebAddress('http:/x')).toBe(true) // the URL parser makes this http://x/
    expect(isWebAddress('mailto:a@b')).toBe(false)
    expect(isWebAddress(undefined)).toBe(false)
  })
})
