import { describe, it, expect } from 'vitest'
import { mainWindowOptions } from '../electron/main/main_window.js'

describe('mainWindowOptions: hardened main window config', () => {
  it('returns window options with hardened webPreferences', () => {
    const opts = mainWindowOptions('/app/preload.cjs')
    expect(opts.webPreferences).toMatchObject({
      preload: '/app/preload.cjs',
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      nodeIntegrationInSubFrames: false,
      webSecurity: true,
      webviewTag: false,
      navigateOnDragDrop: false,
      spellcheck: false
    })
  })

  it('includes basic window dimensions and styling', () => {
    const opts = mainWindowOptions('/app/preload.cjs')
    expect(opts).toMatchObject({
      width: 1280,
      height: 820,
      minWidth: 900,
      minHeight: 600,
      titleBarStyle: 'hiddenInset',
      trafficLightPosition: { x: 18, y: 18 },
      backgroundColor: '#0f1117',
      vibrancy: 'under-window',
      show: false
    })
  })

  it('sandbox is always true for security', () => {
    const opts = mainWindowOptions('/app/preload.cjs')
    expect(opts.webPreferences.sandbox).toBe(true)
  })
})
