// Evidence capture for marvin#1063 (open session focuses the ticket's open chat): drives the built app against a
// sandbox HOME whose ~/.agents/venv/bin/python is a fake launcher answering {"ok": true, "focused": true}, so the real
// session launcher, WezTerm and GitHub are never touched. Two widths (Gil views it narrow on the Mini).
// Usage: HOME=<sandbox> node marvin_button_evidence.mjs <out-dir>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT] = process.argv.slice(2)
const HOME = process.env.HOME
if (!OUT || HOME === os.userInfo().homedir ||  // never the real home: the sandbox must be a different folder
    !fs.existsSync(path.join(HOME, '.agents', 'venv', 'bin', 'python'))) {
  console.error('usage: HOME=<sandbox with a fake ~/.agents/venv/bin/python> node marvin_button_evidence.mjs <out-dir>')
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
  for (const [w, h, name] of [[1280, 900, 'wide'], [860, 900, 'narrow']]) {
    await page.setViewportSize({ width: w, height: h })
    await sleep(name === 'wide' ? 6000 : 800)
    await page.keyboard.press('Escape') // any key skips the boot sequence (BootSequence.jsx)
    await sleep(800)
    await page.evaluate(() => {
      const el = [...document.querySelectorAll('button')].find((e) => e.textContent.trim() === 'MARVIN')
      if (!el) throw new Error('no MARVIN button')
      el.click()
    })
    await page.waitForSelector('input[placeholder="#228"]', { timeout: 10000 })
    await page.fill('input[placeholder="#228"]', '#1063')
    await page.keyboard.press('Enter')
    await page.waitForFunction(() => document.body.innerText.includes('already open'), null, { timeout: 15000 })
    await sleep(600)
    await page.screenshot({ path: `${OUT}/pr-1063-marvin-button-focused-${name}.png`, clip: { x: Math.max(0, w - 560), y: 0, width: 560, height: 300 } })
  }
  console.log('shots in', OUT)
} finally {
  await b?.close().catch(() => {})
  proc.kill('SIGTERM')
}
