import { randomBytes } from 'crypto'
import path from 'path'
import { readFile } from 'fs/promises'
import { MOCKUP_SCHEME, MOCKUP_CSP, mimeFor, resolveMockupPath, mockupRequestAllowed } from './mockups.js'
import { parseShowRequest, checkShowPath, projectFor, viewKind } from './show.js'
import { pickShowBounds } from './show_bounds.js'
import { createWebPane, installWebSession, isLocalHost, isWebAddress, SHOW_WEB_PARTITION } from './show_web.js'

// The `marvin show` windows (G-Eskayo/marvin#715): one small MARVIN window per project, reused. A later show for the
// same project replaces what that window shows and brings it to the front; another project gets its own window.
// Built on the mock-up window (mockup_window.js, #938): an HTML page is served through the same marvin-mockup://
// protocol with the same CSP, on this window's own session, and drawn in an <iframe sandbox="allow-scripts"> so it
// stays clickable but has an opaque origin: no window.api, no parent DOM, no network, no pop-ups, no navigation away.
// Everything else (images, PDFs, markdown, text) is drawn by the Docs viewer (FileView), as in the Docs tab.
// A web address loads in its own isolated view below the header (show_web.js), with "Open in browser" kept in the
// header and the link card as the fallback. A new window opens where Gil last moved one (show_bounds.js).
// Electron is injected so the rules are tested without launching the app.

export const SHOW_PARTITION = 'marvin-show'

// The session rules for show windows: the app page itself (file: in a build, the dev server in development), its
// data:/blob: images and PDF bytes, and marvin-mockup:// for the sandboxed page. Every other request is cancelled, so
// a page that slipped past its CSP still reaches nothing. No permissions, no downloads.
export function showRequestOk(url, devOrigin = null) {
  let u
  try {
    u = new URL(String(url))
  } catch {
    return false
  }
  if (mockupRequestAllowed(url)) return true
  if (['file:', 'data:', 'blob:', 'devtools:'].includes(u.protocol)) return true
  if (devOrigin) {
    try {
      const d = new URL(devOrigin)
      const ws = d.protocol === 'https:' ? 'wss:' : 'ws:'
      if ((u.protocol === d.protocol || u.protocol === ws) && u.host === d.host) return true
    } catch {
      // a bad dev origin allows nothing extra
    }
  }
  return false
}

export function installShowSession(ses, handler, { devOrigin = null } = {}) {
  ses.webRequest.onBeforeRequest((details, callback) => {
    // file: is the app's own bundle; a page in the sandboxed frame can't load file: (Chromium refuses it to a
    // non-file origin, and the frame's CSP has no file:), so only the app page itself ever asks for it.
    callback({ cancel: !showRequestOk(details.url, devOrigin) })
  })
  ses.setPermissionRequestHandler?.((_wc, _permission, callback) => callback(false))
  ses.setPermissionCheckHandler?.(() => false)
  ses.on?.('will-download', (event, item) => {
    event.preventDefault?.()
    item?.cancel?.()
  })
  ses.protocol.handle(MOCKUP_SCHEME, handler)
}

// The mock-up CSP, except who may frame the page: the mock-up window refuses every frame ('none'); here the page
// lives in the show window's own frame, so only the app page (file: in a build, the dev server in development) may.
export function showFrameCsp(devOrigin = null) {
  let dev = ''
  try {
    if (devOrigin) dev = ` ${new URL(devOrigin).origin}`
  } catch {
    dev = ''
  }
  return MOCKUP_CSP.replace("frame-ancestors 'none'", `frame-ancestors file:${dev}`)
}

export function createShowWindows({
  BrowserWindow,
  session,
  preload, // the app's preload script: the window's own page reads its item through window.api.show
  loadPage, // (win, hash) => void: the app's page with #show=<project>
  roots = () => [], // allowed folders (show.js allowedRoots)
  context = () => ({}), // { projects, outboxRoot, view, matchOutboxName } for projectFor
  source = null, // mockups.js createMockupSource: PR files, read at the PR's head commit
  prHead = async () => null, // (repo, number) => { sha, ref } | null
  readFileForView, // (fullPath, displayPath, size) => FileView file
  fileFromBuffer, // ({ name, path, size }, buf) => FileView file
  focusApp = () => {},
  newId = () => randomBytes(12).toString('hex'),
  partition = SHOW_PARTITION,
  devOrigin = null,
  backgroundColor = '#05040A', // --bg of the celestial-navigation tokens (#428), as ShowWindow.jsx
  checkPath = checkShowPath,
  WebContentsView = null, // Electron's; without it a web address is only the link card
  webPartition = SHOW_WEB_PARTITION,
  bounds = null, // show_bounds.js createBoundsStore: the last moved show window's place
  screenAreas = () => [] // the screens' work areas, so a saved place on an unplugged screen isn't used
}) {
  const byProject = new Map() // project id -> { win, item, frameId }
  const frames = new Map() // frame id -> { read(file) }, the one HTML page each window shows
  let ses = null
  let webSes = null
  // Local addresses (localhost, the LAN) a shown page may reach: only hosts Gil himself asked to show.
  const localHosts = new Set()
  const csp = showFrameCsp(devOrigin)
  const notFound = (text, status = 404) => new Response(text, { status, headers: { 'content-type': 'text/plain; charset=utf-8', 'content-security-policy': csp } })

  // marvin-mockup://<frame id>/<path inside the page's folder>
  async function handle(request) {
    let url
    try { url = new URL(request.url) } catch { return notFound('bad address', 400) }
    const frame = frames.get(url.hostname)
    if (!frame) return notFound('This page was replaced or its window closed')
    const rawPath = String(request.url).replace(/^[^:]+:\/\/[^/]*/, '').replace(/[?#].*$/, '')
    const file = resolveMockupPath(frame.dir, rawPath, frame.page)
    if (!file) return notFound('outside the page\'s folder', 403)
    const r = await frame.read(file)
    if (!r.ok) return notFound(r.reason || 'not found')
    return new Response(r.body, { status: 200, headers: { 'content-type': r.mime, 'content-security-policy': csp, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' } })
  }

  function ensureSession() {
    if (!ses) {
      ses = session.fromPartition(partition)
      installShowSession(ses, handle, { devOrigin })
    }
    return ses
  }

  function ensureWebSession() {
    if (!webSes) {
      webSes = session.fromPartition(webPartition)
      installWebSession(webSes, localHosts)
    }
    return webSes
  }

  function closeWeb(entry) {
    if (entry?.web) {
      entry.web.close()
      entry.web = null
    }
  }

  // A web address: its page in the window, its state kept on the item so a reloaded window page finds it.
  function openWeb(entry, item) {
    closeWeb(entry)
    if (!WebContentsView || !isWebAddress(item.url)) return
    try {
      const u = new URL(item.url)
      if (isLocalHost(u.hostname)) localHosts.add(u.host.toLowerCase())
    } catch {
      return
    }
    item.web = { state: 'loading', url: item.url }
    // The pane reports its first state while it is being made, before `pane` is set.
    let pane = null
    pane = createWebPane({
      WebContentsView,
      win: entry.win,
      url: item.url,
      partition: webPartition,
      getSession: ensureWebSession,
      onState: (st) => {
        if (entry.item !== item || (pane && entry.web !== pane)) return
        item.web = st
        if (entry.ready && alive(entry)) entry.win.webContents.send('show:web', st)
      }
    })
    entry.web = pane
    if (entry.webBounds) pane.setBounds(entry.webBounds)
  }

  // A local page's folder, read under its real directory only (resolveMockupPath keeps it inside `dir`). A symlink
  // inside the folder pointing out is checked like any other shown path.
  function localFrame(real) {
    const base = path.dirname(real)
    return {
      dir: '',
      page: path.basename(real),
      async read(rel) {
        const full = path.join(base, rel)
        const ok = checkPath(full, { roots: [base] })
        if (!ok.ok) return { ok: false, reason: ok.reason }
        try {
          return { ok: true, body: await readFile(ok.real), mime: mimeFor(rel) }
        } catch {
          return { ok: false, reason: 'not found' }
        }
      }
    }
  }

  function prFrame(target, file) {
    const dir = path.posix.dirname(file) === '.' ? '' : path.posix.dirname(file)
    return { dir, page: path.posix.basename(file), read: (rel) => source.read(target, rel) }
  }

  // The request -> { ok, item } with the item's project, label and how to read it, or { ok: false, reason }.
  async function resolve(body) {
    const parsed = parseShowRequest(body)
    if (!parsed.ok) return parsed
    const req = parsed.req
    const ctx = context() || {}
    if (req.kind === 'url') {
      const project = projectFor(req, ctx)
      return { ok: true, item: { kind: 'link', url: req.url, label: req.label || req.url, project } }
    }
    if (req.kind === 'file') {
      const c = checkPath(req.path, { roots: roots() })
      if (!c.ok) return c
      const project = projectFor(req, { ...ctx, real: c.real })
      const label = req.label || path.basename(c.real)
      const kind = viewKind(c.real)
      return { ok: true, item: { kind, label, path: c.real, size: c.size, project, read: { local: c.real } } }
    }
    // A PR file: read at the PR's head commit (or the named branch), from the local clone or GitHub.
    if (!source) return { ok: false, reason: 'PR files can\'t be read on this Mac' }
    let target = { repo: req.repo, number: req.number, ref: req.ref, sha: null }
    if (req.number) {
      const head = await prHead(req.repo, req.number).catch(() => null)
      if (!head) return { ok: false, reason: `PR #${req.number} wasn't found in ${req.repo}` }
      target = { ...target, sha: head.sha || null, ref: head.ref || req.ref }
    }
    const first = await source.read(target, req.path)
    if (!first.ok) return { ok: false, reason: first.reason || 'not found on the branch' }
    const project = projectFor(req, ctx)
    const label = req.label || `${path.posix.basename(req.path)}${req.number ? ` · PR #${req.number}` : ''}`
    return { ok: true, item: { kind: viewKind(req.path), label, path: req.path, size: first.body.length, project, pr: { repo: req.repo, number: req.number, ref: target.ref }, read: { target, file: req.path, first } } }
  }

  function makeWindow(project) {
    ensureSession()
    let areas = []
    try { areas = screenAreas() || [] } catch { areas = [] }
    const place = pickShowBounds(bounds?.load?.() ?? null, areas)
    const win = new BrowserWindow({
      ...place,
      ...('x' in place ? {} : { center: true }),
      minWidth: 420,
      minHeight: 360,
      title: `MARVIN · ${project.name}`,
      backgroundColor,
      show: false,
      autoHideMenuBar: true,
      webPreferences: {
        partition,
        preload,
        sandbox: false, // the app's own preload, as the main window; the untrusted page is the sandboxed frame
        contextIsolation: true,
        nodeIntegration: false,
        nodeIntegrationInSubFrames: false,
        webSecurity: true,
        webviewTag: false,
        navigateOnDragDrop: false,
        spellcheck: false
      }
    })
    const wc = win.webContents
    win.on('page-title-updated', (event) => event.preventDefault())
    wc.setWindowOpenHandler(() => ({ action: 'deny' }))
    // The window's own page never navigates (links go through window.api), and the frame stays on its own page.
    wc.on('will-navigate', (event) => event.preventDefault())
    wc.on('will-redirect', (event) => event.preventDefault())
    wc.on('will-frame-navigate', (event) => {
      if (event?.isMainFrame) return
      if (!mockupRequestAllowed(event?.url)) event.preventDefault?.()
    })
    wc.on('will-attach-webview', (event) => event.preventDefault())
    const entry = { win, item: null, frameId: null, ready: false, web: null, webBounds: null }
    // Moved or resized by Gil: the next new window opens here, at this size ("moved" and "resized" fire once,
    // when the drag ends).
    const remember = () => {
      if (!win.isDestroyed?.() && bounds?.save) bounds.save(win.getBounds())
    }
    win.on('moved', remember)
    win.on('resized', remember)
    win.once('ready-to-show', () => {
      entry.ready = true
      win.show()
      win.focus?.()
    })
    win.on('closed', () => {
      closeWeb(entry)
      if (entry.frameId) frames.delete(entry.frameId)
      if (byProject.get(project.id) === entry) byProject.delete(project.id)
    })
    byProject.set(project.id, entry)
    loadPage(win, `show=${encodeURIComponent(project.id)}`)
    return entry
  }

  const alive = (entry) => entry && entry.win && !entry.win.isDestroyed?.()

  // Show one item. Returns { ok, project, window: 'opened' | 'reused', label } or { ok: false, reason }.
  async function show(body) {
    const r = await resolve(body)
    if (!r.ok) return { ok: false, reason: r.reason }
    const item = r.item
    const project = item.project
    // Two shows racing for one project: the window is made once (the second finds the first's entry).
    let entry = byProject.get(project.id)
    let reused = alive(entry)
    if (!reused) entry = makeWindow(project)
    if (entry.frameId) frames.delete(entry.frameId)
    entry.frameId = null
    if (item.kind === 'html') {
      const id = newId()
      frames.set(id, item.read.local ? localFrame(item.read.local) : prFrame(item.read.target, item.read.file))
      entry.frameId = id
      item.frameUrl = `${MOCKUP_SCHEME}://${id}/${encodeURIComponent(frames.get(id).page)}`
    }
    closeWeb(entry)
    entry.item = item
    // Closed while this show was being resolved (or a moment before): open it again rather than lose the item.
    if (!alive(entry)) {
      entry = makeWindow(project)
      entry.item = item
      reused = false
    }
    const win = entry.win
    if (item.kind === 'link') openWeb(entry, item)
    if (entry.ready) win.webContents.send('show:item', publicItem(item))
    if (win.isMinimized?.()) win.restore()
    if (entry.ready) win.show()
    win.focus?.()
    focusApp()
    return { ok: true, project: project.id, projectName: project.name, window: reused ? 'reused' : 'opened', label: item.label, kind: item.kind }
  }

  // What the window's page is told about its item (never the read handle).
  function publicItem(item) {
    if (!item) return null
    const { read: _read, ...rest } = item
    return rest
  }

  const entryOf = (webContents) => [...byProject.values()].find((e) => alive(e) && e.win.webContents === webContents) || null

  // The window's page asks for its current item and its file (IPC, by the asking window).
  function current(webContents) {
    return publicItem(entryOf(webContents)?.item)
  }

  async function read(webContents) {
    const item = entryOf(webContents)?.item
    if (!item) return null
    if (item.kind === 'link' || item.kind === 'html') return null
    // The file's own name decides how it is drawn; a --label ("A screenshot from earlier") is only the title.
    if (item.read.local) return readFileForView(item.read.local, path.basename(item.read.local), item.size)
    const buf = item.read.first?.ok ? item.read.first.body : null
    if (!buf) return { name: item.label, path: item.path, kind: 'other', reason: 'This file is gone from the branch' }
    return fileFromBuffer({ name: path.posix.basename(item.path), path: item.path, size: buf.length }, buf)
  }

  // The window's page says where the web page goes (the area under its header), in window coordinates.
  function setWebBounds(webContents, rect) {
    const entry = entryOf(webContents)
    if (!entry) return null
    entry.webBounds = rect && typeof rect === 'object' ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null
    return entry.web && entry.webBounds ? entry.web.setBounds(entry.webBounds) : null
  }

  function itemOf(webContents) {
    return entryOf(webContents)?.item || null
  }

  // An image a shown markdown file embeds (`shots/x.png`), next to that file: inside the allowed folders for a local
  // file, on the same commit for a PR file. { ok, dataUrl } | { ok: false, reason }.
  async function image(webContents, src) {
    const item = itemOf(webContents)
    const no = (reason) => ({ ok: false, reason })
    if (!item || !item.read) return no('nothing shown')
    if (typeof src !== 'string' || !src.trim() || /^([a-z][a-z0-9+.-]*:|\/\/|\/)/i.test(src)) return no('not a file next to this one')
    let clean
    try {
      clean = decodeURIComponent(src.split(/[?#]/)[0])
    } catch {
      return no('bad image path')
    }
    if (item.read.local) {
      const c = checkPath(path.resolve(path.dirname(item.read.local), clean), { roots: roots() })
      if (!c.ok) return no(c.reason)
      const f = readFileForView(c.real, path.basename(c.real), c.size)
      return f.kind === 'image' ? { ok: true, dataUrl: f.dataUrl } : no(f.reason || 'not an image')
    }
    const joined = path.posix.normalize(path.posix.join(path.posix.dirname(item.read.file), clean))
    if (joined.startsWith('..') || joined.startsWith('/')) return no('outside the repo')
    const r = await source.read(item.read.target, joined)
    if (!r.ok) return no(r.reason || 'not found')
    const f = fileFromBuffer({ name: path.posix.basename(joined), path: joined, size: r.body.length }, r.body)
    return f.kind === 'image' ? { ok: true, dataUrl: f.dataUrl } : no(f.reason || 'not an image')
  }

  return { show, current, read, image, itemOf, setWebBounds, handle, _byProject: byProject, _frames: frames }
}
