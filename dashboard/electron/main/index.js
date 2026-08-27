import { app, BrowserWindow, ipcMain, dialog } from 'electron'
import { join } from 'path'
import { existsSync } from 'fs'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { listSubsystems, readHistory, buildIndex } from './metrics.js'
import { listPipelinePrs, approveMr, denyMr, fetchTicketContext } from './mr_review.js'

const execFileAsync = promisify(execFile)

// Overridable via env for pointing at a real n8n webhook once G-Eskayo/marvin#11's
// "exact n8n node topology" downstream work exists; defaults to the reference
// receiver in dashboard/webhook-server/ (see its README for the contract).
const MR_WEBHOOK_URL = process.env.MARVIN_MR_WEBHOOK_URL || 'http://localhost:7878/approve'
// Same reference receiver, second endpoint -- ADR 0025's Deny action.
const MR_DENY_WEBHOOK_URL = process.env.MARVIN_MR_DENY_WEBHOOK_URL || 'http://localhost:7878/deny'

async function listOpenPrs() {
  const { stdout } = await execFileAsync('gh', [
    'pr',
    'list',
    '--repo',
    'G-Eskayo/marvin',
    '--state',
    'open',
    '--json',
    'number,title,url,body'
  ])
  return JSON.parse(stdout)
}

async function ghIssueView(issueNumber) {
  const { stdout } = await execFileAsync('gh', [
    'issue',
    'view',
    String(issueNumber),
    '--repo',
    'G-Eskayo/marvin',
    '--json',
    'number,title,body'
  ])
  return JSON.parse(stdout)
}

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

function postJson(webhookUrl, body) {
  return fetch(webhookUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
}

function registerMrReviewHandlers() {
  ipcMain.handle('mr:list', () => listPipelinePrs(listOpenPrs))

  // Live-fetches the linked ticket's (and its parent PRD's) requirements/
  // design/tasks for the detail view, per the "link back, don't duplicate"
  // decision in G-Eskayo/marvin#72's evidence schema (ADR 0024).
  ipcMain.handle('mr:ticketContext', (_event, ticketRef) => fetchTicketContext(ticketRef, ghIssueView))

  // The actual "unambiguous, no risk of accidental merge from a stray click"
  // requirement (G-Eskayo/marvin#11's acceptance criteria) lives here, not in
  // the renderer -- a native OS-level confirm dialog can't be spoofed by a
  // fast double-click the way a custom in-page confirm affordance could.
  ipcMain.handle('mr:approve', async (_event, { number, url }) => {
    const { response } = await dialog.showMessageBox(mainWindow, {
      type: 'warning',
      buttons: ['Cancel', 'Merge PR'],
      defaultId: 0,
      cancelId: 0,
      message: `Merge PR #${number}?`,
      detail: `This fires the approval webhook and merges ${url} via gh pr merge. This can't be undone from here.`
    })
    if (response !== 1) {
      return { merged: false, cancelled: true }
    }
    await approveMr(url, MR_WEBHOOK_URL, postJson)
    return { merged: true, cancelled: false }
  })

  // Same native-dialog defense as mr:approve -- both of Deny's terminal
  // actions have real, visible side effects on GitHub (ADR 0025), and
  // "drop" specifically closes the PR and ticket with no undo.
  ipcMain.handle('mr:deny', async (_event, { number, url, ticketNumber, action, reasons, comment }) => {
    const isDrop = action === 'drop'
    const { response } = await dialog.showMessageBox(mainWindow, {
      type: 'warning',
      buttons: ['Cancel', isDrop ? 'Drop PR & Ticket' : 'Send Feedback'],
      defaultId: 0,
      cancelId: 0,
      message: isDrop ? `Drop PR #${number} and close its ticket?` : `Send deny feedback on PR #${number}?`,
      detail: isDrop
        ? `This closes ${url} and its ticket via gh. No re-engagement is expected. This can't be undone from here.`
        : `This comments the structured feedback on ${url} and its ticket, then releases the claim for a future review/debug/improve pass.`
    })
    if (response !== 1) {
      return { done: false, cancelled: true }
    }
    await denyMr({ prUrl: url, ticketNumber, action, reasons, comment }, MR_DENY_WEBHOOK_URL, postJson)
    return { done: true, cancelled: false }
  })
}

app.whenReady().then(() => {
  registerMetricsHandlers()
  registerMrReviewHandlers()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
