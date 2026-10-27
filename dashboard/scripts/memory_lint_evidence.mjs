// Evidence for marvin#695 (Health ▸ "Memory links and index are sound"). Drives the built app in its own Electron
// against a sandbox HOME whose memory folder is a small generic fixture (a broken link, a typo'd link, a note missing
// from MEMORY.md), and a stand-in health_checks.py that writes only the real memory:lint check.
// Usage: HOME=<sandbox dir> node memory_lint_evidence.mjs <out>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'
const APP = path.resolve(import.meta.dirname, '..'), [OUT] = process.argv.slice(2)
if (!OUT || !process.env.HOME?.includes('sandbox')) { console.error('usage: HOME=<sandbox> node memory_lint_evidence.mjs <out>'); process.exit(1) }
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
let b; for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 5000 }) } catch { await sleep(250) } }
let page; for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
await page.setViewportSize({ width: 1280, height: 900 })
await sleep(14000)
const click = (sel, text) => page.evaluate(([s, t]) => {
  const el = [...document.querySelectorAll(s)].find((e) => !t || e.textContent.trim().startsWith(t) || e.textContent.includes(t))
  if (!el) throw new Error(`no ${s} ${t || ''}`)
  el.click()
}, [sel, text])
const shot = async (name) => { await sleep(900); await page.screenshot({ path: `${OUT}/695-${name}.png` }); console.log('shot', name) }
try {
  await click('button', 'Health'); await sleep(1500); await shot('01-health-card')
  await click('[data-check-id="memory:lint"]'); await sleep(800); await shot('02-drilldown')
} finally { await b.close(); proc.kill('SIGTERM') }
