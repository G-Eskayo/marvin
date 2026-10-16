// Evidence capture for #102 (Proposals): drives the built app against a sandbox HOME (fake gh + wezterm), never the
// real store. Usage: HOME=<sandbox> node proposals_evidence.mjs <out-dir> <scenario: full|empty|error>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'
const APP = path.resolve(import.meta.dirname, '..'), [OUT, SCENARIO] = process.argv.slice(2)
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
let b; for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page; for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
const tall = SCENARIO === 'full' ? 1500 : 700
await page.setViewportSize({ width: 1280, height: tall })
await sleep(9000)
const click = (sel, text) => page.evaluate(([s, t]) => {
  const el = [...document.querySelectorAll(s)].find((e) => !t || e.textContent.trim().startsWith(t))
  if (!el) throw new Error(`no ${s} ${t || ''}`)
  el.click()
}, [sel, text])
const type = (sel, value) => page.evaluate(([s, v]) => {
  const el = document.querySelector(s)
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v)
  el.dispatchEvent(new Event('input', { bubbles: true }))
}, [sel, value])
const shot = async (name) => { await sleep(700); await page.screenshot({ path: `${OUT}/102-${name}.png` }); console.log('shot', name) }
try {
  await click('button', 'MR Review'); await sleep(800)
  await click('button', 'Proposals'); await sleep(1500)
  if (SCENARIO !== 'full') { await shot(`state-${SCENARIO}`); process.exit(0) }
  await shot('01-list')
  const c1 = '[data-proposal^="hand-small"]', c2 = '[data-proposal^="turn-the"]', c3 = '[data-proposal^="a-weekly"]'
  await click(`${c1} button`, '▸ Technical'); await click(`${c1} [data-action="snooze"]`); await shot('02-details-and-snooze-menu')
  await click(`${c1} [data-action="snooze"]`)
  await click(`${c1} [data-action="ticket"]`); await sleep(2500); await shot('03-ticket-made')
  await click(`${c3} [data-action="ask"]`); await sleep(2500); await shot('04-ask-marvin')
  await click(`${c2} [data-action="dismiss"]`); await click(`${c2} [data-dismiss="until"]`); await sleep(300)
  await click('[role="dialog"] button', 'Create one'); await sleep(200)
  await click('[role="dialog"] button[type="submit"]'); await shot('05-until-needs-a-title')
  await type('[role="dialog"] input[placeholder="What the new ticket is for"]', 'Shared offline speech package exists')
  await shot('06-until-filled')
  await click('[role="dialog"] button[type="submit"]'); await sleep(2500); await shot('07-until-done')
  await click(`${c3} [data-action="dismiss"]`); await click(`${c3} [data-dismiss="reason"]`); await sleep(300)
  await type('[role="dialog"] textarea', 'Not now: I want to try this by hand for a month first')
  await shot('08-reason-dialog')
  await click('[role="dialog"] button[type="submit"]'); await sleep(2500); await shot('09-all-done')
} finally { await b.close(); proc.kill('SIGTERM') }
