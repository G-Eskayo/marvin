// `marvin show` windows (G-Eskayo/marvin#715) with Electron faked: one window per project, reused; a window closed
// mid-show; two shows racing; the sandboxed page's protocol and network block. Real files in a throwaway folder.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { EventEmitter } from 'events'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, realpathSync, symlinkSync, unlinkSync, lstatSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { createShowWindows, installShowSession, showRequestOk, showFrameCsp, SHOW_PARTITION } from '../electron/main/show_window.js'
import { readFileForView, fileFromBuffer } from '../electron/main/outbox.js'
import { checkShowPath } from '../electron/main/show.js'

let root
beforeEach(() => { root = realpathSync(mkdtempSync(path.join(tmpdir(), 'show-win-'))) })
afterEach(() => rmSync(root, { recursive: true, force: true }))
const put = (rel, data = 'x') => {
  const full = path.join(root, rel)
  mkdirSync(path.dirname(full), { recursive: true })
  writeFileSync(full, data)
  return full
}
// The test folder is under the OS temp dir, which the real check refuses; this one judges roots only.
const checkPath = (p, opts) => {
  const r = checkShowPath(p, opts)
  if (!r.ok && /temp folder/.test(r.reason)) {
    const real = realpathSync(p)
    const inside = (opts.roots || []).some((x) => real === x || real.startsWith(x + path.sep))
    if (!inside) return { ok: false, reason: 'Outside the folders MARVIN shows from' }
    const st = lstatSync(real)
    return st.isFile() ? { ok: true, real, size: st.size } : { ok: false, reason: 'Only a file can be shown, not a folder' }
  }
  return r
}

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
      this.destroyed = false
      this.webContents = new EventEmitter()
      this.webContents.send = vi.fn()
      this.webContents.setWindowOpenHandler = (fn) => { this.openHandler = fn }
      this.focus = vi.fn()
      this.show = vi.fn()
      this.restore = vi.fn()
      this.isMinimized = () => false
      this.isDestroyed = () => this.destroyed
      windows.push(this)
    }
    ready() { this.emit('ready-to-show') }
    close() { this.destroyed = true; this.emit('closed') }
  }
  const session = { fromPartition: vi.fn((p) => (sessions[p] ||= fakeSession())) }
  return { BrowserWindow, session, sessions, windows }
}

const PROJECTS = () => [
  { id: 'marvin', name: 'MARVIN', repo: 'G-Eskayo/marvin', localPaths: [path.join(root, 'agents')] },
  { id: 'seal', name: 'Seal Speak', repo: 'G-Eskayo/clarity-captions', localPaths: [path.join(root, 'cc')] }
]

function make(extra = {}) {
  const e = fakeElectron()
  const loadPage = vi.fn()
  const focusApp = vi.fn()
  let n = 0
  const sw = createShowWindows({
    BrowserWindow: e.BrowserWindow,
    session: e.session,
    preload: '/app/preload.cjs',
    loadPage,
    roots: () => [path.join(root, 'agents'), path.join(root, 'cc'), path.join(root, 'outbox')],
    context: () => ({ projects: PROJECTS(), outboxRoot: path.join(root, 'outbox') }),
    readFileForView,
    fileFromBuffer,
    focusApp,
    newId: () => `f${++n}`,
    checkPath,
    ...extra
  })
  return { ...e, sw, loadPage, focusApp }
}

describe('one window per project, reused', () => {
  it('opens a window for a project, then reuses it for the next item, and brings it forward each time', async () => {
    const a = put('agents/docs/a.md', '# A')
    const b = put('agents/docs/b.png', 'not really a png')
    const { sw, windows, loadPage, focusApp } = make()
    const r1 = await sw.show({ kind: 'file', path: a })
    expect(r1).toMatchObject({ ok: true, project: 'marvin', window: 'opened' })
    expect(windows).toHaveLength(1)
    expect(loadPage).toHaveBeenCalledWith(windows[0], 'show=marvin')
    windows[0].ready()
    const r2 = await sw.show({ kind: 'file', path: b })
    expect(r2).toMatchObject({ ok: true, project: 'marvin', window: 'reused' })
    expect(windows).toHaveLength(1)
    expect(windows[0].webContents.send).toHaveBeenLastCalledWith('show:item', expect.objectContaining({ label: 'b.png', kind: 'image' }))
    expect(windows[0].focus).toHaveBeenCalled()
    expect(focusApp).toHaveBeenCalledTimes(2)
  })

  it('two projects at once: each gets its own window, and each keeps its own item', async () => {
    const a = put('agents/a.md', '# A')
    const s = put('cc/s.md', '# S')
    const { sw, windows } = make()
    const [r1, r2] = await Promise.all([sw.show({ kind: 'file', path: a }), sw.show({ kind: 'file', path: s })])
    expect([r1.project, r2.project]).toEqual(['marvin', 'seal'])
    expect(windows).toHaveLength(2)
    expect(sw.current(windows[0].webContents).label).toBe('a.md')
    expect(sw.current(windows[1].webContents).label).toBe('s.md')
    expect((await sw.read(windows[1].webContents)).content).toBe('# S')
  })

  it('two shows racing for one project make one window, and the later item wins', async () => {
    const a = put('agents/a.md', 'A')
    const b = put('agents/b.md', 'B')
    const { sw, windows } = make()
    await Promise.all([sw.show({ kind: 'file', path: a }), sw.show({ kind: 'file', path: b })])
    expect(windows).toHaveLength(1)
    expect(sw.current(windows[0].webContents).label).toBe('b.md')
  })

  it('a window Gil closed is opened again by the next show (closed mid-show too)', async () => {
    const a = put('agents/a.md', 'A')
    const { sw, windows } = make()
    await sw.show({ kind: 'file', path: a })
    windows[0].close()
    const r = await sw.show({ kind: 'file', path: a })
    expect(r.window).toBe('opened')
    expect(windows).toHaveLength(2)
    // Closed after the show found it but before it was told the item: the item is not lost.
    let closeNext = true
    const slow = make({ prHead: async () => ({ sha: 'a'.repeat(40) }) })
    await slow.sw.show({ kind: 'file', path: a })
    slow.windows[0].ready()
    const orig = slow.windows[0].webContents.send
    slow.windows[0].isDestroyed = () => { if (closeNext) { closeNext = false; return false } return true }
    const r2 = await slow.sw.show({ kind: 'file', path: a })
    expect(r2.ok).toBe(true)
    expect(slow.windows.length).toBe(2)
    expect(orig).not.toHaveBeenCalledWith('show:item', expect.anything(), expect.anything())
  })

  it('a refused path opens nothing', async () => {
    put('secret/x.png')
    const { sw, windows } = make()
    for (const body of [{ kind: 'file', path: path.join(root, 'secret/x.png') }, { kind: 'file', path: path.join(root, 'agents/../secret/x.png') }, { kind: 'file', path: path.join(root, 'agents/missing.png') }, { kind: 'nope' }]) {
      const r = await sw.show(body)
      expect(r.ok, JSON.stringify(body)).toBe(false)
    }
    expect(windows).toHaveLength(0)
  })

  it('the window is the app page on its own sandboxed session, never navigating away', async () => {
    const a = put('agents/a.md', 'A')
    const { sw, windows, sessions } = make()
    await sw.show({ kind: 'file', path: a })
    const w = windows[0]
    expect(w.opts.webPreferences).toMatchObject({ partition: SHOW_PARTITION, contextIsolation: true, nodeIntegration: false, nodeIntegrationInSubFrames: false, webviewTag: false, preload: '/app/preload.cjs' })
    expect(w.openHandler()).toEqual({ action: 'deny' })
    const nav = { preventDefault: vi.fn() }
    w.webContents.emit('will-navigate', nav, 'https://evil.example/')
    expect(nav.preventDefault).toHaveBeenCalled()
    const frameNav = { isMainFrame: false, url: 'https://evil.example/', preventDefault: vi.fn() }
    w.webContents.emit('will-frame-navigate', frameNav)
    expect(frameNav.preventDefault).toHaveBeenCalled()
    expect(sessions[SHOW_PARTITION].scheme).toBe('marvin-mockup')
  })

  it('a label is only the title: the file\'s own name decides how it is drawn (found live: a label hid an image)', async () => {
    const png = put('agents/shot.png', Buffer.from('89504e470d0a1a0a0000000d49484452', 'hex'))
    const { sw, windows } = make()
    await sw.show({ kind: 'file', path: png, label: 'A screenshot from earlier' })
    expect(sw.current(windows[0].webContents).label).toBe('A screenshot from earlier')
    expect((await sw.read(windows[0].webContents)).kind).toBe('image')
  })

  it('a huge file shows as a card, not a frozen window', async () => {
    const big = put('agents/huge.png', Buffer.alloc(16 * 1024 * 1024, 1))
    const { sw, windows } = make()
    await sw.show({ kind: 'file', path: big })
    const f = await sw.read(windows[0].webContents)
    expect(f.kind).toBe('other')
    expect(f.reason).toMatch(/Too large/)
  })

  it('a file deleted after it was shown reads as gone, not an error thrown', async () => {
    const a = put('agents/a.md', 'A')
    const { sw, windows } = make()
    await sw.show({ kind: 'file', path: a })
    unlinkSync(a)
    const f = await sw.read(windows[0].webContents)
    expect(f.kind).toBe('other')
    expect(f.reason).toMatch(/gone/)
  })
})

describe('HTML in the sandboxed frame', () => {
  const page = '<script>try{parent.document.title="x"}catch(e){};fetch("https://evil.example/")</script><script src="app.js"></script>'

  it('serves the page and its own folder only, with the mock-up CSP, and nothing once replaced', async () => {
    const html = put('agents/docs/design/m/index.html', page)
    put('agents/docs/design/m/app.js', 'window.x=1')
    put('agents/docs/secret.md', 'no')
    const { sw, windows, sessions } = make()
    const r = await sw.show({ kind: 'file', path: html })
    expect(r.kind).toBe('html')
    const item = sw.current(windows[0].webContents)
    expect(item.frameUrl).toBe('marvin-mockup://f1/index.html')
    expect(item.read).toBeUndefined() // the page never sees how files are read
    const h = sessions[SHOW_PARTITION].handler
    const ok = await h({ url: 'marvin-mockup://f1/index.html' })
    expect(ok.status).toBe(200)
    expect(ok.headers.get('content-security-policy')).toMatch(/connect-src marvin-mockup:/)
    // Only the app page may frame it (a real run found the mock-up CSP's frame-ancestors 'none' blanked the frame).
    expect(ok.headers.get('content-security-policy')).toMatch(/frame-ancestors file:(;|$)/)
    expect(showFrameCsp('http://localhost:5173/x')).toMatch(/frame-ancestors file: http:\/\/localhost:5173(;|$)/)
    expect(showFrameCsp('not a url')).toMatch(/frame-ancestors file:(;|$)/)
    expect((await h({ url: 'marvin-mockup://f1/app.js' })).status).toBe(200)
    for (const u of ['marvin-mockup://f1/../secret.md', 'marvin-mockup://f1/%2e%2e/secret.md', 'marvin-mockup://f1/%252e%252e/secret.md', 'marvin-mockup://f1/..%2fsecret.md', 'marvin-mockup://zzz/index.html']) {
      expect((await h({ url: u })).status, u).not.toBe(200)
    }
    // A symlink in the page's folder pointing out is refused like any other path.
    symlinkSync(path.join(root, 'agents/docs/secret.md'), path.join(root, 'agents/docs/design/m/leak.md'))
    expect((await h({ url: 'marvin-mockup://f1/leak.md' })).status).not.toBe(200)
    // The next show replaces the page: the old frame id serves nothing.
    windows[0].ready()
    await sw.show({ kind: 'file', path: put('agents/n.md', 'n') })
    expect((await h({ url: 'marvin-mockup://f1/index.html' })).status).toBe(404)
  })

  it('the session cancels every request but the app page and the sandboxed page', () => {
    for (const u of ['file:///app/out/renderer/index.html', 'marvin-mockup://f1/index.html', 'data:image/png;base64,AA', 'blob:file:///x']) expect(showRequestOk(u), u).toBe(true)
    for (const u of ['https://evil.example/', 'http://127.0.0.1:7879/show', 'ws://evil/', 'prmedia://media/x', 'javascript:alert(1)']) expect(showRequestOk(u), u).toBe(false)
    expect(showRequestOk('http://localhost:5173/src/main.jsx', 'http://localhost:5173')).toBe(true)
    expect(showRequestOk('ws://localhost:5173/', 'http://localhost:5173')).toBe(true)
    expect(showRequestOk('http://localhost:5174/', 'http://localhost:5173')).toBe(false)
    const ses = fakeSession()
    installShowSession(ses, () => {})
    const cb = vi.fn()
    ses.permission(null, 'media', cb)
    expect(cb).toHaveBeenCalledWith(false)
    const item = { cancel: vi.fn() }
    ses.emit('will-download', { preventDefault: vi.fn() }, item)
    expect(item.cancel).toHaveBeenCalled()
  })
})

describe('PR files', () => {
  const sha = 'a990349dbd151f99eb4e17b84b150935aa673bb3'
  const files = { 'docs/design/m/index.html': '<p>mock</p>', 'docs/design/m/shot.png': Buffer.from('89504e470d0a1a0a0000000d49484452', 'hex'), 'docs/plan.md': '# Plan\n![s](design/m/shot.png)' }
  const source = { read: vi.fn(async (_t, f) => (f in files ? { ok: true, body: Buffer.from(files[f]), mime: 'text/html' } : { ok: false, reason: 'gone' })) }

  it('reads a PR file at the head commit and opens it in its repo\'s project window', async () => {
    const { sw, windows } = make({ source, prHead: async () => ({ sha, ref: 'design/924' }) })
    const r = await sw.show({ kind: 'pr', repo: 'G-Eskayo/marvin', number: 934, path: 'docs/plan.md' })
    expect(r).toMatchObject({ ok: true, project: 'marvin' })
    expect(source.read).toHaveBeenCalledWith(expect.objectContaining({ sha, number: 934 }), 'docs/plan.md')
    expect((await sw.read(windows[0].webContents)).content).toMatch(/# Plan/)
    const img = await sw.image(windows[0].webContents, 'design/m/shot.png')
    expect(img.ok).toBe(true)
    expect((await sw.image(windows[0].webContents, '../../etc/passwd')).ok).toBe(false)
    expect((await sw.image(windows[0].webContents, '/etc/passwd')).ok).toBe(false)
  })

  it('a deleted branch or a missing PR is a plain refusal, no window', async () => {
    const { sw, windows } = make({ source, prHead: async () => null })
    expect((await sw.show({ kind: 'pr', repo: 'G-Eskayo/marvin', number: 9999, path: 'docs/plan.md' })).reason).toMatch(/wasn't found/)
    const gone = make({ source, prHead: async () => ({ sha }) })
    expect((await gone.sw.show({ kind: 'pr', repo: 'G-Eskayo/marvin', number: 934, path: 'docs/nope.md' })).ok).toBe(false)
    expect(windows.length + gone.windows.length).toBe(0)
  })

  it('a web address is a link card in the named project\'s window', async () => {
    const { sw, windows } = make()
    const r = await sw.show({ kind: 'url', url: 'https://example.com/', project: 'seal' })
    expect(r).toMatchObject({ ok: true, project: 'seal', kind: 'link' })
    expect(await sw.read(windows[0].webContents)).toBeNull()
  })
})
