// Evidence for marvin#691 (Health ▸ "Code graph is current" + "Rebuild graph now"). Drives the built app in its own
// Electron against a sandbox HOME whose ~/.agents is a small real git repo with a real graphify graph three commits
// behind, and a stand-in health_checks.py that writes only the real graphify:fresh check. The rebuild runs the real
// graphify_freshness.py refresh and real `graphify update` (GRAPHIFY_BIN).
// Usage: HOME=<sandbox dir> GRAPHIFY_BIN=<graphify> node graphify_freshness_evidence.mjs <out>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'
const APP = path.resolve(import.meta.dirname, '..'), [OUT] = process.argv.slice(2)
if (!OUT || !process.env.HOME?.includes('sandbox')) { console.error('usage: HOME=<sandbox> node graphify_freshness_evidence.mjs <out>'); process.exit(1) }
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
const shot = async (name) => { await sleep(900); await page.screenshot({ path: `${OUT}/691-${name}.png` }); console.log('shot', name) }
try {
  await click('button', 'Health'); await sleep(1500); await shot('01-health-card-yellow')
  await click('[data-check-id="graphify:fresh"]'); await sleep(800); await shot('02-drilldown-rebuild-button')
  await click('button', 'Rebuild graph now')
  for (let i = 0; i < 120; i++) { if (!(await page.evaluate(() => document.body.innerText.includes('Rebuilding')))) break; await sleep(500) }
  await shot('03-after-rebuild-green')
  await click('button', 'Back to all checks'); await sleep(800); await shot('04-health-card-green')
} finally { await b.close(); proc.kill('SIGTERM') }
