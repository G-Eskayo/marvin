// Evidence for stuck PRs: gathers the count of merge ops in error/reengaged/interrupted state,
// whose GitHub head may or may not match their recorded head. Used to measure the recurrence of
// stuck cards in production (e.g. 2026-11-26 check: how often do bare pushes leave a card hung?).
// Usage: node stuck_ops_evidence.mjs <output.json>
import fs from 'fs'
import path from 'path'
import { chromium } from 'playwright-core'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT] = process.argv.slice(2)
if (!OUT) {
  console.error('usage: node stuck_ops_evidence.mjs <output.json>')
  process.exit(1)
}

const execFileAsync = promisify(execFile)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function getRunningDashboardPort() {
  try {
    // Query the running dashboard's debug port via its IPC port file, or default to localhost:4000
    // The dashboard, when running normally, listens on localhost:4000 for CDP connections by default.
    // Try a few common ports.
    const ports = [9222, 9223, 9224, 9225]
    for (const port of ports) {
      try {
        const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`)
        await browser.close()
        return port
      } catch {
        // Not on this port, try next
      }
    }
    throw new Error('Could not find running dashboard on any common CDP port')
  } catch (err) {
    throw new Error(`Failed to locate running dashboard: ${err?.message || err}`)
  }
}

async function getStuckOpsFromRunningApp() {
  let browser = null
  try {
    const port = await getRunningDashboardPort()
    for (let i = 0; i < 120; i++) {
      try {
        browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`)
        break
      } catch {
        await sleep(250)
      }
    }
    if (!browser) throw new Error('Could not connect to running dashboard')
    await sleep(500) // Let the connection settle

    const context = browser.contexts()[0]
    const page = context?.pages()[0]
    if (!page) throw new Error('No dashboard window found')

    // Ask the electron main process for stuck ops via IPC
    const stuckOps = await page.evaluate(async () => {
      return new Promise((resolve, reject) => {
        if (!window.electronAPI?.invoke) {
          reject(new Error('electronAPI.invoke not available in preload'))
          return
        }
        window.electronAPI
          .invoke('mr:stuckOps', [])
          .then((ops) => resolve(ops || []))
          .catch((err) => reject(err))
      })
    })

    if (!Array.isArray(stuckOps)) throw new Error('Invalid response from dashboard main process')
    return stuckOps
  } finally {
    await browser?.close()
  }
}

const stuckOps = await getStuckOpsFromRunningApp()
const evidence = {
  timestamp: new Date().toISOString(),
  stuckOpsCount: stuckOps.length,
  stuckOps: stuckOps.map((op) => ({
    url: op.url,
    repo: op.repo,
    number: op.number,
    head: op.head
  }))
}

fs.mkdirSync(path.dirname(OUT), { recursive: true })
fs.writeFileSync(OUT, JSON.stringify(evidence, null, 2))
console.log(JSON.stringify({ count: stuckOps.length, path: OUT }))
