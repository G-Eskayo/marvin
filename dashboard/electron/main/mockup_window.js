import { randomBytes } from 'crypto'
import path from 'path'
import { MOCKUP_SCHEME, MOCKUP_CSP, cleanPagePath, mockupRequestAllowed, resolveMockupPath } from './mockups.js'

// The mock-up window (G-Eskayo/marvin#938): a PR's clickable mock-up opened inside MARVIN, read from the PR's head
// commit through the marvin-mockup:// protocol. It runs on its own session partition, sandboxed, with no preload (so
// no window.api), no Node, every non-mockup request cancelled, no pop-ups and no navigation away. Electron is
// injected (BrowserWindow, session) so the rules are tested without launching the app.

export const MOCKUP_PARTITION = 'marvin-mockup'

// The session rules, applied once to the mock-up partition: only marvin-mockup:// loads; no permissions (camera,
// microphone, notifications, clipboard...), no downloads.
export function installMockupSession(ses, handler) {
  ses.webRequest.onBeforeRequest((details, callback) => callback({ cancel: !mockupRequestAllowed(details.url) }))
  ses.setPermissionRequestHandler?.((_wc, _permission, callback) => callback(false))
  ses.setPermissionCheckHandler?.(() => false)
  ses.on?.('will-download', (event, item) => {
    event.preventDefault?.()
    item?.cancel?.()
  })
  ses.protocol.handle(MOCKUP_SCHEME, handler)
}

const sameMockup = (url, id) => {
  try {
    const u = new URL(String(url))
    return u.protocol === `${MOCKUP_SCHEME}:` && u.hostname === id
  } catch {
    return false
  }
}

const notFound = (text, status = 404) => new Response(text, { status, headers: { 'content-type': 'text/plain; charset=utf-8', 'content-security-policy': MOCKUP_CSP } })

export function createMockupWindows({ BrowserWindow, session, source, partition = MOCKUP_PARTITION, newId = () => randomBytes(12).toString('hex'), backgroundColor = '#0f1117' }) {
  const open = new Map() // id -> { target, dir, page, key, win }
  let ses = null

  // marvin-mockup://<id>/<path inside the mock-up's folder>
  async function handle(request) {
    let url
    try { url = new URL(request.url) } catch { return notFound('bad address', 400) }
    const entry = open.get(url.hostname)
    if (!entry) return notFound('This mock-up window is closed')
    // The raw path, before any URL normalising: resolveMockupPath judges traversal itself.
    const rawPath = String(request.url).replace(/^[^:]+:\/\/[^/]*/, '').replace(/[?#].*$/, '')
    const file = resolveMockupPath(entry.dir, rawPath, entry.page)
    if (!file) return notFound('outside the mock-up', 403)
    const r = await source.read(entry.target, file)
    if (!r.ok) return notFound(r.reason || 'not found')
    return new Response(r.body, { status: 200, headers: { 'content-type': r.mime, 'content-security-policy': MOCKUP_CSP, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' } })
  }

  function ensureSession() {
    if (!ses) {
      ses = session.fromPartition(partition)
      installMockupSession(ses, handle)
    }
    return ses
  }

  // args: { repo, number, sha, ref, path } from the renderer. Returns { ok: true } or { ok: false, reason } for the detail.
  async function openMockup(args = {}) {
    const page = cleanPagePath(args.path)
    if (!page) return { ok: false, reason: 'Not a mock-up page' }
    const target = { repo: String(args.repo || ''), sha: String(args.sha || ''), ref: String(args.ref || ''), number: Number(args.number) || null }
    const key = `${target.repo}@${target.sha || target.ref}:${page}`
    for (const entry of open.values()) {
      if (entry.key === key && !entry.win.isDestroyed?.()) {
        if (entry.win.isMinimized?.()) entry.win.restore()
        entry.win.focus()
        return { ok: true, reused: true }
      }
    }
    const first = await source.read(target, page)
    if (!first.ok) return { ok: false, reason: first.reason, gone: first.gone }

    ensureSession()
    const id = newId()
    const dir = path.posix.dirname(page) === '.' ? '' : path.posix.dirname(page)
    const name = dir ? path.posix.basename(dir) : page
    const title = `MARVIN · Mock-up: ${name}${target.number ? ` (#${target.number})` : ''}`
    const win = new BrowserWindow({
      width: 1200,
      height: 880,
      minWidth: 360,
      minHeight: 400,
      title,
      backgroundColor,
      show: false,
      autoHideMenuBar: true,
      webPreferences: {
        partition,
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        nodeIntegrationInSubFrames: false,
        webSecurity: true,
        webviewTag: false,
        navigateOnDragDrop: false,
        spellcheck: false
      }
    })
    const entry = { target, dir, page: path.posix.basename(page), key, win }
    open.set(id, entry)
    const wc = win.webContents
    win.on('page-title-updated', (event) => event.preventDefault()) // keep MARVIN's title, not the page's
    wc.setWindowOpenHandler(() => ({ action: 'deny' }))
    const stay = (event, url) => { if (!sameMockup(url, id)) event.preventDefault() }
    wc.on('will-navigate', stay)
    wc.on('will-redirect', stay)
    wc.on('will-frame-navigate', (event) => { if (!sameMockup(event?.url, id)) event.preventDefault?.() })
    wc.on('will-attach-webview', (event) => event.preventDefault())
    win.once('ready-to-show', () => win.show())
    win.on('closed', () => open.delete(id))
    // A page that fails part-way still shows what it can; the load promise is not the outcome of the open.
    Promise.resolve(win.loadURL(`${MOCKUP_SCHEME}://${id}/${encodeURIComponent(entry.page)}`)).catch(() => {})
    return { ok: true }
  }

  return { open: openMockup, handle, _entries: open }
}
