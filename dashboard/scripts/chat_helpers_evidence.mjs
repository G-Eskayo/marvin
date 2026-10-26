// Evidence capture for marvin#612 (chat helpers in Activity): drives the built app against a sandbox HOME whose
// ~/.claude/logs/jobs holds fixture helper logs (and whose ~/.agents/bin/gh is a fake), never the real store or GitHub.
// One launch, two widths (Gil views it narrow on the Mini). Usage: HOME=<sandbox> node chat_helpers_evidence.mjs <out-dir>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT] = process.argv.slice(2)
const HOME = process.env.HOME
if (!OUT || HOME === '/Users/gileskayo' || !fs.existsSync(path.join(HOME, '.claude', 'logs', 'jobs'))) {
  console.error('usage: HOME=<sandbox with fixture ~/.claude/logs/jobs/helper-*.json> node chat_helpers_evidence.mjs <out-dir>')
  process.exit(1)
}
fs.mkdirSync(OUT, { recursive: true })
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
let b
try {
  for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
  let page
  for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
  await page.setViewportSize({ width: 1280, height: 900 })
  await sleep(6000)
  await page.keyboard.press('Escape') // any key skips the boot sequence (BootSequence.jsx)
  await sleep(800)
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('button')].find((e) => e.textContent.trim().startsWith('Activity'))
    if (!el) throw new Error('no Activity tab')
    el.click()
  })
  await page.waitForSelector('[data-testid="chat-helpers"]', { timeout: 15000 })
  await sleep(1500)
  await page.screenshot({ path: `${OUT}/pr-612-activity-helpers.png` })
  await page.setViewportSize({ width: 860, height: 1000 })
  await sleep(1200)
  await page.screenshot({ path: `${OUT}/pr-612-activity-helpers-narrow.png` })
  console.log('shots in', OUT)
} finally {
  await b?.close().catch(() => {})
  proc.kill('SIGTERM')
}
