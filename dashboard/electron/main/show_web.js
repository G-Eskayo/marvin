// A web address shown by `marvin show` (G-Eskayo/marvin#715, owner's answer on PR #1029: "I do also want it to
// render in the window and have fallbacks of the link to open in browser"). The page loads in its own view inside
// the project's window, below the header, and "Open in browser" stays in the header the whole time. When the page
// can't be drawn (no connection, a certificate error, a refused address, a crashed page) the window falls back to
// the link card with the reason.
//
// The page is untrusted, so it is kept apart from the app: its own in-memory session (nothing saved to disk, no
// cookies shared with the app or Chrome), a sandboxed renderer with no preload and no Node, no permissions, no
// downloads, no pop-ups (a link that would open a new window opens in this same view), and only http(s) pages.
// Addresses on this Mac or the local network are refused unless the shown address is itself one (a dev server
// Gil asked to see), so a page on the internet can't reach the refresh server on 127.0.0.1 or the router.
// Electron is injected so the rules are tested without launching the app.

export const SHOW_WEB_PARTITION = 'marvin-show-web' // no "persist:" prefix: kept in memory only

// Chromium's "aborted" (a navigation replaced by another one): not a failure to show.
const ERR_ABORTED = -3

export function isWebAddress(url) {
  try {
    const u = new URL(String(url))
    return (u.protocol === 'http:' || u.protocol === 'https:') && !!u.hostname
  } catch {
    return false
  }
}

// Loopback, link-local, private ranges and .local names.
export function isLocalHost(hostname) {
  let h = String(hostname || '').toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '')
  if (!h) return true
  if (h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.local') || h.endsWith('.internal')) return true
  if (h.includes(':')) {
    // IPv6: loopback, unspecified, unique-local fc00::/7, link-local fe80::/10, and IPv4-mapped addresses.
    if (h === '::1' || h === '::') return true
    if (/^f[cd][0-9a-f]{0,2}:/.test(h) || /^fe[89ab][0-9a-f]?:/.test(h)) return true
    // The URL parser writes ::ffff:127.0.0.1 as ::ffff:7f00:1.
    const mapped = h.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/)
    const hex = h.match(/^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/)
    if (mapped) h = mapped[1]
    else if (hex) {
      const hi = parseInt(hex[1], 16)
      const lo = parseInt(hex[2], 16)
      h = `${hi >> 8}.${hi & 255}.${lo >> 8}.${lo & 255}`
    } else return false
  }
  const m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/)
  if (!m) {
    // a bare number or hex form ("2130706433", "0x7f000001") is an IPv4 address in disguise
    return /^(0x[0-9a-f]+|\d+)$/.test(h)
  }
  const [a, b] = [Number(m[1]), Number(m[2])]
  return a === 0 || a === 127 || a === 10 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127)
}

// May the shown page (or anything it loads) request this address? `localHosts` is the set of local hosts Gil
// himself asked to show.
export function webRequestOk(url, localHosts = new Set()) {
  let u
  try {
    u = new URL(String(url))
  } catch {
    return false
  }
  if (u.protocol === 'data:' || u.protocol === 'blob:') return true
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(u.protocol)) return false
  if (isLocalHost(u.hostname)) return localHosts.has(u.host.toLowerCase())
  return true
}

export function installWebSession(ses, localHosts) {
  ses.webRequest.onBeforeRequest((details, callback) => callback({ cancel: !webRequestOk(details.url, localHosts) }))
  ses.setPermissionRequestHandler?.((_wc, _permission, callback) => callback(false))
  ses.setPermissionCheckHandler?.(() => false)
  ses.on?.('will-download', (event, item) => {
    event.preventDefault?.()
    item?.cancel?.()
  })
}

// The rectangle the window's page asks the view to fill, kept inside the window's content area.
export function clampViewBounds(rect, content) {
  const n = (v) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : null)
  const W = n(content?.width) ?? 0
  const H = n(content?.height) ?? 0
  const x = Math.min(Math.max(n(rect?.x) ?? 0, 0), W)
  const y = Math.min(Math.max(n(rect?.y) ?? 0, 0), H)
  const width = Math.min(Math.max(n(rect?.width) ?? 0, 0), W - x)
  const height = Math.min(Math.max(n(rect?.height) ?? 0, 0), H - y)
  return { x, y, width, height }
}

// One web page in one show window. onState({ state: 'loading' | 'loaded' | 'failed', url, reason? }) tells the
// window's page what to draw. The view is attached once the page has something to draw (dom-ready), so until then,
// and after a failure, the window's own page shows through: "Loading…", or the link card with the reason.
export function createWebPane({ WebContentsView, win, url, onState, partition = SHOW_WEB_PARTITION, getSession }) {
  getSession?.()
  const view = new WebContentsView({
    webPreferences: {
      partition,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      nodeIntegrationInSubFrames: false,
      webviewTag: false,
      webSecurity: true,
      navigateOnDragDrop: false,
      spellcheck: false,
      safeDialogs: true
    }
  })
  const wc = view.webContents
  let attached = false
  let closed = false
  // Set by a failed load until the next main-frame navigation: Chromium then commits its own error page and sends
  // dom-ready for it (found live), which must not lay a blank page over the card.
  let failed = false
  let bounds = null
  let current = url
  const tell = (s) => { if (!closed) onState({ ...s, url: current }) }

  const attach = () => {
    if (attached || closed || win.isDestroyed?.()) return
    win.contentView.addChildView(view)
    if (bounds) view.setBounds(bounds)
    attached = true
  }
  const detach = () => {
    if (!attached) return
    try { win.contentView.removeChildView(view) } catch { /* window already gone */ }
    attached = false
  }
  const fail = (reason) => {
    failed = true
    detach()
    tell({ state: 'failed', reason })
  }

  wc.setWindowOpenHandler?.(({ url: next }) => {
    // A link that would open a new window opens here instead (never a pop-up, never another app).
    if (isWebAddress(next)) wc.loadURL(next).catch?.(() => {})
    return { action: 'deny' }
  })
  const guard = (event, next) => {
    const to = typeof next === 'string' ? next : event?.url
    if (!isWebAddress(to)) event.preventDefault?.()
  }
  wc.on('will-navigate', guard)
  wc.on('will-redirect', guard)
  wc.on('will-attach-webview', (event) => event.preventDefault?.())
  wc.on('did-start-navigation', (_e, _to, isInPlace, isMainFrame) => {
    if (isMainFrame && !isInPlace) failed = false
  })
  wc.on('dom-ready', () => {
    if (failed) return
    attach()
    tell({ state: 'loaded' })
  })
  wc.on('did-navigate', (_e, to) => {
    if (typeof to === 'string') current = to
    if (attached) tell({ state: 'loaded' })
  })
  wc.on('did-navigate-in-page', (_e, to, isMainFrame) => {
    if (isMainFrame !== false && typeof to === 'string') current = to
    if (attached) tell({ state: 'loaded' })
  })
  wc.on('did-fail-load', (_e, code, description, failedUrl, isMainFrame) => {
    if (isMainFrame === false || code === ERR_ABORTED) return
    if (typeof failedUrl === 'string' && failedUrl) current = failedUrl
    fail(`The page couldn't be loaded here (${description || `error ${code}`})`)
  })
  wc.on('render-process-gone', () => fail('The page stopped working in MARVIN'))

  if (!isWebAddress(url)) {
    queueMicrotask(() => fail('Only web pages (http or https) open in MARVIN'))
  } else {
    tell({ state: 'loading' })
    Promise.resolve(wc.loadURL(url)).catch(() => {
      // did-fail-load has already said why; a load that rejects without it still falls back
      if (!closed && !attached && !failed) fail('The page couldn\'t be loaded here')
    })
  }

  return {
    view,
    get url() { return current },
    get attached() { return attached },
    setBounds(rect) {
      bounds = clampViewBounds(rect, win.getContentBounds?.() || { width: rect?.width, height: rect?.height })
      if (attached) view.setBounds(bounds)
      return bounds
    },
    close() {
      if (closed) return
      detach()
      closed = true
      try { wc.close?.() } catch { /* already closed */ }
    }
  }
}
