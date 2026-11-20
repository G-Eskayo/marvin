export function mainWindowOptions(preload) {
  return {
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 18, y: 18 },
    backgroundColor: '#0f1117',
    vibrancy: 'under-window',
    show: false,
    webPreferences: {
      preload,
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      nodeIntegrationInSubFrames: false,
      webSecurity: true,
      webviewTag: false,
      navigateOnDragDrop: false,
      spellcheck: false
    }
  }
}

export function createMainWindow({ BrowserWindow, preload }) {
  return new BrowserWindow(mainWindowOptions(preload))
}
