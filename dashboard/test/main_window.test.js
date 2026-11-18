// Main window (singular): created on demand, nulled when closed, reused while running.
// ensure() makes it if it's gone, window() returns it, send() pipes IPC safely.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { EventEmitter } from 'events'
import { createMainWindow } from '../electron/main/main_window.js'

function fakeElectron() {
  const windows = []
  class BrowserWindow extends EventEmitter {
    constructor(opts) {
      super()
      this.opts = opts
      this.destroyed = false
      this.webContents = new EventEmitter()
      this.webContents.send = vi.fn()
      this.show = vi.fn()
      windows.push(this)
    }
    isDestroyed() {
      return this.destroyed
    }
    close() {
      this.destroyed = true
      this.emit('closed')
    }
    // Split isDestroyed from 'closed' event for testing: mark destroyed separately, emit closed manually
    setDestroyed(destroyed) {
      this.destroyed = destroyed
    }
    emitClosed() {
      this.emit('closed')
    }
  }
  return { BrowserWindow, windows }
}

describe('main_window', () => {
  let e
  let preload
  let loadPage
  let mainWin

  beforeEach(() => {
    e = fakeElectron()
    preload = '/path/to/preload.cjs'
    loadPage = vi.fn()
    mainWin = createMainWindow({
      BrowserWindow: e.BrowserWindow,
      preload,
      loadPage
    })
  })

  it('1. ensure() creates the window if it does not exist', () => {
    const win = mainWin.ensure()
    expect(win).toBeDefined()
    expect(win.isDestroyed()).toBe(false)
    expect(e.windows).toHaveLength(1)
  })

  it('2. ensure() reuses the window if it already exists', () => {
    const win1 = mainWin.ensure()
    const win2 = mainWin.ensure()
    expect(win1).toBe(win2)
    expect(e.windows).toHaveLength(1)
  })

  it('3. window() returns the current window', () => {
    const ensured = mainWin.ensure()
    const returned = mainWin.window()
    expect(returned).toBe(ensured)
  })

  it('4. window() returns null if no window has been created', () => {
    const returned = mainWin.window()
    expect(returned).toBeNull()
  })

  it('5. send() delivers a message to the window', () => {
    mainWin.ensure()
    mainWin.send('test:channel', 'arg1', 'arg2')
    expect(e.windows[0].webContents.send).toHaveBeenCalledWith('test:channel', 'arg1', 'arg2')
  })

  it('6. send() does nothing if the window is destroyed', () => {
    const win = mainWin.ensure()
    win.close()
    mainWin.send('test:channel', 'arg')
    expect(win.webContents.send).not.toHaveBeenCalled()
  })

  it('7. closed event nulls the reference exactly once (identity check prevents double-handling)', () => {
    const winA = mainWin.ensure()
    expect(mainWin.window()).toBe(winA)
    // Close window A so a new window is created, but don't emit closed yet
    winA.setDestroyed(true)
    const winB = mainWin.ensure()
    expect(mainWin.window()).toBe(winB)
    expect(e.windows).toHaveLength(2)
    // Fire winA's closed event after winB was created: identity check should prevent nulling winB
    winA.emitClosed()
    expect(mainWin.window()).toBe(winB)
  })

  it('8. ensure() recreates the window after it is closed', () => {
    const win1 = mainWin.ensure()
    win1.close()
    const win2 = mainWin.ensure()
    expect(win2).not.toBe(win1)
    expect(win2.isDestroyed()).toBe(false)
    expect(e.windows).toHaveLength(2)
  })

  it('calls loadPage with the window', () => {
    mainWin.ensure()
    expect(loadPage).toHaveBeenCalledWith(e.windows[0])
  })

  it('emits ready-to-show and calls show', () => {
    const win = mainWin.ensure()
    expect(win.show).not.toHaveBeenCalled()
    win.emit('ready-to-show')
    expect(win.show).toHaveBeenCalled()
  })

  it('passes webPreferencesExtra to BrowserWindow', () => {
    const extraPrefs = { devTools: true }
    const mainWin2 = createMainWindow({
      BrowserWindow: e.BrowserWindow,
      preload,
      loadPage,
      webPreferencesExtra: extraPrefs
    })
    mainWin2.ensure()
    expect(e.windows[0].opts.webPreferences).toMatchObject({
      preload,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
      devTools: true
    })
  })
})
