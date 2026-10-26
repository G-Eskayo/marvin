// Evidence for the headless helped side (ADR 0073 amendment): sandbox HOME with a saved cache and a stand-in support.py.
// Usage: HOME=<sandbox> node support_headless_evidence.mjs <out>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'
const APP = path.resolve(import.meta.dirname, '..'), [OUT] = process.argv.slice(2)
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
let b; for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page; for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
await page.setViewportSize({ width: 1280, height: 900 })
await sleep(14000)
const click = (sel, text) => page.evaluate(([s, t]) => {
  const el = [...document.querySelectorAll(s)].find((e) => !t || e.textContent.trim().startsWith(t) || e.textContent.includes(t))
  if (!el) throw new Error(`no ${s} ${t || ''}`)
  el.click()
}, [sel, text])
const shot = async (name) => { await sleep(900); await page.screenshot({ path: `${OUT}/665-${name}.png` }); console.log('shot', name) }
try {
  await click('button', 'Support'); await sleep(800)
  await click('button', "won't build"); await sleep(1500); await shot('01-helped-fix-runs-by-itself')
  await click('button', 'What is the Docs'); await sleep(1500); await shot('02-helped-explained-got-it')
} finally { await b.close(); proc.kill('SIGTERM') }
