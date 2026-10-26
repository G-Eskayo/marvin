// Evidence capture for #661 (support link, ADR 0073): drives the built app against a sandbox HOME (a saved support
// cache and a stand-in support.py), never the real one. Usage: HOME=<sandbox> node support_evidence.mjs <out> <helper|helped>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'
const APP = path.resolve(import.meta.dirname, '..'), [OUT, ROLE] = process.argv.slice(2)
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
let b; for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page; for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
await page.setViewportSize({ width: 1280, height: 1000 })
await sleep(14000)
const click = (sel, text) => page.evaluate(([s, t]) => {
  const el = [...document.querySelectorAll(s)].find((e) => !t || e.textContent.trim().startsWith(t) || e.textContent.includes(t))
  if (!el) throw new Error(`no ${s} ${t || ''}`)
  el.click()
}, [sel, text])
const shot = async (name) => { await sleep(900); await page.screenshot({ path: `${OUT}/661-${name}.png` }); console.log('shot', name) }
try {
  if (ROLE === 'helper') {
    await click('button', 'Support'); await sleep(800)
    await click('button', 'Handled by MARVIN'); await shot('01-helper-needs-you-and-outcomes')
    await click('button', 'gh says my token'); await sleep(1500); await shot('02-helper-verified-thread')
    await click('button', 'Dashboard won'); await sleep(1500); await click('button', 'Draft with MARVIN'); await sleep(1500); await shot('03-helper-reply-with-check')
    await click('button', 'Preview for them'); await sleep(1500); await shot('09-helper-preview-for-them')
  } else {
    await click('button', 'IT'); await sleep(800); await shot('04-helped-it-panel')
    await click('button', 'Docs tab shows'); await sleep(1500); await shot('05-helped-reply-waiting-apply')
    await click('button', 'Done ('); await click('button', 'gh says my token'); await sleep(1500); await shot('06-helped-fixed-and-verified')
    await click('button', 'IT'); await sleep(600); await click('label', 'I have an idea'); await sleep(400); await shot('07-helped-it-idea-mode')
    await click('button', 'IT'); await sleep(400); await click('button', 'A skill that turns'); await sleep(1500); await shot('08-helped-ideas')
  }
} finally { await b.close(); proc.kill('SIGTERM') }
