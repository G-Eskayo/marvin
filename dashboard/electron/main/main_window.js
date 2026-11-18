// Main dashboard window (singular): created on demand, nulled when closed, reused while running.
// The pattern: ensure() makes it if it's gone, window() returns it, send() pipes IPC safely to it.
// A closed event nulls the reference (guard at index.js:398-399 already protects against double-handling).

export function createMainWindow({ BrowserWindow, preload, loadPage, webPreferencesExtra = {} }) {
  let mainWindow = null

  const alive = (win) => win && !win.isDestroyed?.()

  function ensure() {
    if (!alive(mainWindow)) {
      const created = new BrowserWindow({
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
          sandbox: false,
          ...webPreferencesExtra
        }
      })

      created.on('ready-to-show', () => {
        if (alive(created)) created.show()
      })

      mainWindow = created
      created.on('closed', () => {
        if (mainWindow === created) mainWindow = null
      })

      loadPage(created)
    }
    return mainWindow
  }

  function getWindow() {
    return mainWindow
  }

  function send(channel, ...args) {
    if (alive(mainWindow)) {
      mainWindow.webContents.send(channel, ...args)
    }
  }

  return { ensure, window: getWindow, send }
}
