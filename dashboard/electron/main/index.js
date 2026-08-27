import { app, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'
import { existsSync } from 'fs'
import { listSubsystems, readHistory, buildIndex } from './metrics.js'

process.env['ELECTRON_DISABLE_SECURITY_WARNINGS'] = 'true'

let mainWindow = null

function createWindow() {
  mainWindow = new BrowserWindow({
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
      preload: (() => {
        // electron-vite outputs .cjs when package.json has "type":"module"
        const cjs = join(__dirname, '../preload/index.cjs')
        return existsSync(cjs) ? cjs : join(__dirname, '../preload/index.js')
      })(),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  const devUrl = process.env['ELECTRON_RENDERER_URL']
  if (devUrl) {
    mainWindow.loadURL(devUrl)
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(join(__dirname, '../../out/renderer/index.html'))
  }
}

function registerMetricsHandlers() {
  ipcMain.handle('metrics:index', () => buildIndex())
  ipcMain.handle('metrics:subsystems', () => listSubsystems())
  ipcMain.handle('metrics:history', (_event, subsystem) => readHistory(subsystem))
}

app.whenReady().then(() => {
  registerMetricsHandlers()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
