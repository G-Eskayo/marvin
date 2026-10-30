// Live brain-map wallpaper for Linux (mac-mini-2012, ADR 0069): the Linux counterpart of DesktopLive/main.swift.
// One borderless window per screen at the desktop layer, ignoring the mouse, showing brain-map/index.html in wallpaper
// mode and fed by the same hooks and timers as the macOS host. Pure logic lives in host.js (tested by host.test.js).
//   ~/.agents/dashboard/node_modules/.bin/electron ~/.agents/brain-map/desktop-live-linux/main.js
'use strict'
const { app, BrowserWindow, screen } = require('electron')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { execFile, execFileSync } = require('child_process')
const h = require('./host.js')

const BRAIN = path.resolve(__dirname, '..')
const PAGE = path.join(BRAIN, 'index.html')
const TREE = path.join(BRAIN, 'tree-data.json')
const ACTIVITY = path.join(BRAIN, 'activity.jsonl')
const DEMO = path.join(BRAIN, 'demo-events.jsonl')
const NETWORK = path.join(os.homedir(), '.claude', 'marvin-network.json')
const LOG = path.join(os.homedir(), '.claude', 'logs', 'desktoplive.log')
const STALL_MS = 60_000   // a page that stops drawing this long is reloaded (main.swift's liveness check, #176)

const windows = new Map()            // display id -> BrowserWindow
let lastTreeMtime = 0
let activityLast = null
let demoCount = 0
let liveness = {}
let lastFrames = -1
let lastFrameChange = Date.now()

function log(...parts) {
  try { fs.appendFileSync(LOG, `${new Date().toISOString()} linux ${parts.join(' ')}\n`) } catch { /* logging never stops the wallpaper */ }
}

function read(file) {
  try { return fs.readFileSync(file, 'utf8') } catch { return null }
}

function eachPage(js) {
  for (const w of windows.values()) if (!w.isDestroyed()) w.webContents.executeJavaScript(js).catch(() => {})
}

function lineCount(file) {
  return h.newLines(read(file), 0).count
}

// Electron's own type: 'desktop' fails on this X server ("Add _NET_WM_WINDOW_TYPE_DESKTOP to kAtomsToCache") and
// the window lands ON TOP of everything (found 2026-10-16). Set the type with xprop while the window is still
// unmapped, which is when the window manager reads it: it then sits behind every window, like a real wallpaper.
function setDesktopType(w) {
  const buf = w.getNativeWindowHandle()
  const xid = buf.length >= 8 ? buf.readBigUInt64LE(0) : buf.readUInt32LE(0)
  execFileSync('xprop', ['-id', String(xid), '-f', '_NET_WM_WINDOW_TYPE', '32a',
                         '-set', '_NET_WM_WINDOW_TYPE', '_NET_WM_WINDOW_TYPE_DESKTOP'], { timeout: 5000 })
}

function makeWindow(display) {
  const { x, y, width, height } = display.bounds
  const w = new BrowserWindow({
    x, y, width, height,
    frame: false,   // no Electron type 'desktop': on X11 it makes an unmanaged window that draws over everything resizable: false, movable: false, focusable: false, skipTaskbar: true,
    hasShadow: false, backgroundColor: '#000000', show: false,
    webPreferences: { backgroundThrottling: false, contextIsolation: true, nodeIntegration: false, sandbox: true },
  })
  w.setIgnoreMouseEvents(true)
  try { setDesktopType(w) } catch (e) { log('xprop-failed', e.message); w.destroy(); throw e }   // never show it on top
  w.loadFile(PAGE, { query: { wallpaper: '1' } })
  w.once('ready-to-show', () => w.showInactive())
  w.webContents.on('render-process-gone', (_e, d) => { log('page-crash', d.reason); w.loadFile(PAGE, { query: { wallpaper: '1' } }) })
  w.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  w.webContents.on('will-navigate', (e) => e.preventDefault())
  return w
}

function reconcile() {
  const seen = new Set()
  for (const d of screen.getAllDisplays()) {
    seen.add(d.id)
    const w = windows.get(d.id)
    if (!w || w.isDestroyed()) windows.set(d.id, makeWindow(d))
    else w.setBounds(d.bounds)
  }
  for (const [id, w] of windows) if (!seen.has(id)) { w.destroy(); windows.delete(id) }
  log('screens', windows.size)
}

function checkTree() {
  let m = 0
  try { m = fs.statSync(TREE).mtimeMs } catch { return }
  if (m === lastTreeMtime) return
  lastTreeMtime = m
  const js = h.treeCall(read(TREE))
  if (js) eachPage(js)
  else { log('page-reload', 'tree-data.json did not parse'); for (const w of windows.values()) w.reload() }
}

// By the last line seen, not the count: the file is trimmed to 500 lines, so a full file's count never changes.
function checkActivity() {
  const { lines, last } = h.linesAfter(read(ACTIVITY), activityLast)
  activityLast = last
  for (const js of h.activityCalls(lines)) eachPage(js)
}
function checkFile(file, count, toCalls) {
  const { lines, count: next } = h.newLines(read(file), count)
  for (const js of toCalls(lines)) eachPage(js)
  return next
}

function checkDevices() {
  const ts = ['/usr/bin/tailscale', '/usr/local/bin/tailscale'].find((p) => fs.existsSync(p))
  if (!ts) return
  execFile(ts, ['status', '--json'], { timeout: 10_000 }, (err, stdout) => {
    if (err) return
    let status, registry
    try { status = JSON.parse(stdout); registry = JSON.parse(read(NETWORK) || '{}') } catch { return }
    const r = h.livenessCalls(status, registry, liveness)
    liveness = r.last
    for (const js of r.calls) eachPage(js)
  })
}

function renderFrame() {
  for (const w of windows.values()) {
    if (w.isDestroyed()) continue
    w.webContents.executeJavaScript('window.renderFrame ? (window.renderFrame(performance.now()), window.framesDrawn) : -1')
      .then((frames) => {
        if (frames !== lastFrames) { lastFrames = frames; lastFrameChange = Date.now() }
      }).catch(() => {})
  }
}

function checkStall() {
  if (Date.now() - lastFrameChange < STALL_MS) return
  log('page-reload', 'no new frame for', STALL_MS / 1000, 's')
  lastFrameChange = Date.now()
  for (const w of windows.values()) if (!w.isDestroyed()) w.reload()
}

if (!app.requestSingleInstanceLock()) app.exit(0)   // one wallpaper per session; a second launch just leaves
app.disableHardwareAcceleration()   // Ivy Bridge GPU: software canvas is steadier for a 24 fps ambient view
app.whenReady().then(() => {
  log('start', PAGE)
  activityLast = h.linesAfter(read(ACTIVITY), null, true).last
  demoCount = lineCount(DEMO)
  try { lastTreeMtime = fs.statSync(TREE).mtimeMs } catch { /* first generate.py run creates it */ }
  reconcile()
  screen.on('display-added', reconcile)
  screen.on('display-removed', reconcile)
  screen.on('display-metrics-changed', reconcile)
  setInterval(checkTree, 30_000)
  setInterval(checkActivity, 2_000)
  setInterval(() => { demoCount = checkFile(DEMO, demoCount, h.demoCalls) }, 1_000)
  setInterval(checkDevices, 18_000)
  setTimeout(checkDevices, 3_000)
  setInterval(renderFrame, 1000 / 24)
  setInterval(checkStall, 5_000)
})
app.on('window-all-closed', (e) => e.preventDefault())
