// Evidence for marvin#954 (the box's dashboard reads GitHub from the Mini's feed): run ON mac-mini-2012 against its real
// HOME and its real copy of the feed. Launches this checkout's built app, opens MR Review, screenshots the window, and
// keeps the app's own output so the "gh auth login" lines can be counted. Never calls GitHub (the box can't).
// Usage (on the box, after `npx electron-vite build`): DISPLAY=:0 node scripts/box_feed_evidence.mjs <out.png> <app.log> [seconds]
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT, LOG, SECS = '20'] = process.argv.slice(2)
if (!OUT || !LOG) { console.error('usage: node box_feed_evidence.mjs <out.png> <app.log> [seconds]'); process.exit(1) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const log = fs.openSync(LOG, 'w')
const env = { ...process.env, MARVIN_EVIDENCE_CAPTURE: '1', MARVIN_DASHBOARD_REFRESH_PORT: String(await freePort()) }
const proc = spawn(path.join(APP, 'node_modules/electron/dist/electron'), [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env, stdio: ['ignore', log, log] })
let b
for (let i = 0; i < 160 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page
for (let i = 0; i < 80 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
try {
  await page.setViewportSize({ width: 1280, height: 900 })
  await sleep(8000)
  await page.locator('button', { hasText: 'MR Review' }).first().click()
  await sleep(Number(SECS) * 1000)
  await page.screenshot({ path: OUT })
  console.log('shot', OUT)
} finally {
  await b.close()
  proc.kill('SIGTERM')
}
