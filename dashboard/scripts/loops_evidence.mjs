// Evidence for marvin#1123: Vitals > Loops and the "Can MARVIN reach you?" row, in the built app against a sandbox HOME
// holding sample health, run logs and alerts (never the real machine's). Two widths.
// Usage: HOME=<sandbox with ~/.agents linked to this checkout and ~/.claude/logs sample data> node loops_evidence.mjs <out-dir>
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
if (!OUT || HOME === os.userInfo().homedir || !fs.existsSync(path.join(HOME, '.claude', 'logs', 'health-status.json'))) {
  console.error('usage: HOME=<sandbox with ~/.claude/logs/health-status.json> node loops_evidence.mjs <out-dir>')
  process.exit(1)
}
fs.mkdirSync(OUT, { recursive: true })
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
const click = (page, re) => page.evaluate((src) => {
  const re = new RegExp(src)
  const el = [...document.querySelectorAll('button')].find((e) => re.test(e.textContent.trim()))
  if (!el) throw new Error(`no button ${src}`)
  el.click()
}, re)
let b
try {
  for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
  let page
  for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
  for (const [w, name] of [[1280, 'wide'], [860, 'narrow']]) {
    await page.setViewportSize({ width: w, height: 1100 })
    await sleep(name === 'wide' ? 6000 : 800)
    await page.keyboard.press('Escape')
    await sleep(800)
    await click(page, '^(Health|Vitals)$')
    await sleep(800)
    await click(page, '^Checks$')
    await page.waitForSelector('[data-testid="reach-row"]', { timeout: 20000 })
    await sleep(1000)
    await page.screenshot({ path: `${OUT}/pr-1123-reach-${name}.png`, clip: { x: 0, y: 0, width: w, height: 520 } })
    await click(page, '^Loops$')
    await page.waitForSelector('[data-testid="loops-panel"]', { timeout: 20000 })
    await sleep(1200)
    await page.screenshot({ path: `${OUT}/pr-1123-loops-${name}.png`, clip: { x: 0, y: 0, width: w, height: 1100 } })
    if (name === 'wide') {
      await click(page, '^All$')
      await sleep(800)
      await page.screenshot({ path: `${OUT}/pr-1123-loops-all-${name}.png`, fullPage: true })
    }
  }
  console.log('shots in', OUT)
} finally {
  await b?.close().catch(() => {})
  proc.kill('SIGTERM')
}
