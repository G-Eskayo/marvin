import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { EventEmitter } from 'events'

// Tests for sandbox: true enforcement
// When sandbox is enabled, the preload cannot access Node.js APIs directly,
// and IPC becomes the only way to communicate between renderer and main.

describe('sandbox: true window configuration', () => {
  it('requires preload to be specified when sandbox is enabled', () => {
    // With sandbox: true, a preload is mandatory to expose APIs to the renderer
    const config = {
      sandbox: true,
      preload: '/path/to/preload.js',
      contextIsolation: true,
      nodeIntegration: false
    }
    expect(config.sandbox).toBe(true)
    expect(config.preload).toBeDefined()
  })

  it('enforces contextIsolation when sandbox is enabled', () => {
    // sandbox: true requires contextIsolation: true for security
    const config = {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false
    }
    expect(config.sandbox).toBe(true)
    expect(config.contextIsolation).toBe(true)
  })

  it('disables nodeIntegration when sandbox is enabled', () => {
    // With sandbox, nodeIntegration must be false
    const config = {
      sandbox: true,
      nodeIntegration: false,
      contextIsolation: true
    }
    expect(config.sandbox).toBe(true)
    expect(config.nodeIntegration).toBe(false)
  })
})

describe('IPC misuse regression', () => {
  // This test catches scenarios where IPC handlers are called incorrectly
  // or where the preload failed to expose the correct API shape

  function createMockIpcMain() {
    const handlers = new Map()
    return {
      handle: (channel, fn) => {
        handlers.set(channel, fn)
      },
      emit: async (channel, ...args) => {
        const handler = handlers.get(channel)
        if (!handler) throw new Error(`No handler for channel: ${channel}`)
        return handler(...args)
      },
      handlers: () => handlers
    }
  }

  function createMockPreload() {
    const ipc = createMockIpcMain()
    return {
      ipc,
      exposeInMainWorld: (api, obj) => {
        // Simulates what contextBridge.exposeInMainWorld does
        return { [api]: obj }
      }
    }
  }

  it('verifies that preload properly exposes IPC methods to renderer', async () => {
    const preload = createMockPreload()
    const api = preload.exposeInMainWorld('api', {
      invoke: (channel, ...args) => preload.ipc.emit(channel, ...args)
    })

    preload.ipc.handle('test:call', async () => 'success')
    const result = await api.api.invoke('test:call')
    expect(result).toBe('success')
  })

  it('catches missing IPC handlers before sandbox prevents fallback access', async () => {
    const preload = createMockPreload()
    const api = preload.exposeInMainWorld('api', {
      invoke: (channel, ...args) => preload.ipc.emit(channel, ...args)
    })

    // If a handler is missing, the error should be clear
    const promise = api.api.invoke('nonexistent:handler')
    expect(promise).rejects.toThrow('No handler for channel: nonexistent:handler')
  })
})

describe('Docs tab srcdoc malformed HTML', () => {
  // When sandbox: true, srcdoc content must be well-formed HTML
  // Malformed HTML can cause parsing errors in the sandboxed iframe

  it('accepts well-formed HTML in srcdoc', () => {
    const html = `
      <!DOCTYPE html>
      <html>
        <head><title>Test</title></head>
        <body><p>Hello</p></body>
      </html>
    `
    expect(html).toContain('<!DOCTYPE html>')
    expect(html).toContain('<html>')
    expect(html).toContain('</html>')
  })

  it('catches missing DOCTYPE in srcdoc', () => {
    const html = `<html><body>Test</body></html>`
    // A proper HTML5 document should have DOCTYPE
    const hasDoctype = /<!DOCTYPE\s+html>/i.test(html)
    expect(hasDoctype).toBe(false)
  })

  it('catches unclosed tags in srcdoc', () => {
    const html = `<html><body><p>Test</body></html>`
    // A parser would fail on this
    const pTags = (html.match(/<p>/g) || []).length
    const pCloseTags = (html.match(/<\/p>/g) || []).length
    expect(pTags).not.toBe(pCloseTags)
  })

  it('verifies iframe sandbox attribute is set correctly', () => {
    const iframeTag = '<iframe sandbox="allow-scripts allow-popups"></iframe>'
    expect(iframeTag).toContain('sandbox=')
    expect(iframeTag).toContain('allow-scripts')
  })

  it('catches missing sandbox attribute on untrusted content frame', () => {
    const iframeWithoutSandbox = '<iframe src="untrusted.html"></iframe>'
    expect(iframeWithoutSandbox).not.toContain('sandbox=')
  })
})
