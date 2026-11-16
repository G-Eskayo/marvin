export function createMainWindowTracker() {
  let mainWindow = null

  return {
    set(win) {
      // Guard against a stale window nulling a newer one
      const created = win
      created.on('closed', () => {
        if (mainWindow === created) mainWindow = null
      })
      mainWindow = win
    },

    get() {
      return mainWindow
    },

    isAlive() {
      return mainWindow && !mainWindow.isDestroyed()
    },

    send(channel, ...args) {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send(channel, ...args)
      }
    }
  }
}
