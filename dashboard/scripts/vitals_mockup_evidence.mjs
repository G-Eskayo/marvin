// Captures for the Vitals tab mock-up (marvin#873): the built app, on this Mac's live data, both placements at 860,
// 1080 and 1440 px plus the vertical monitor (1080 x 1920), a row pointed at (its part lit on the map), its evidence
// open, and the Accounts card at full width and under 900 px. A throwaway copy of the app: its own profile folder, the
// evidence-capture flag (no modal dialogs, refresh port 0), never Gil's window or storage.
//
// Usage: npx electron-vite build && node scripts/vitals_mockup_evidence.mjs <out-dir>
//   MARVIN_CAPTURE_MAP_DIR=<brain-map dir>   the map to draw (default: the installed one)
//   MARVIN_CAPTURE_ACCOUNTS=<file>           a saved accounts sweep (the Mac mini's; this Mac has none of its own)
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const OUT = process.argv[2]
if (!OUT) { console.error('usage: node scripts/vitals_mockup_evidence.mjs <out-dir>'); process.exit(1) }
fs.mkdirSync(OUT, { recursive: true })
const bin = process.platform === 'darwin' ? path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron') : path.join(APP, 'node_modules/electron/dist/electron')
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'vitals-capture-profile-'))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
let browser
const shots = []
try {
  for (let i = 0; i < 120 && !browser; i++) { try { browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
  if (!browser) throw new Error('could not attach to the app')
  let page
  for (let i = 0; i < 80 && !page; i++) { page = browser.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools://')); if (!page) await sleep(250) }
  if (!page) throw new Error('no app window')
  await page.waitForLoadState('domcontentloaded')
  // The switch, as Gil would flip it; then skip the boot sequence.
  await page.evaluate(() => localStorage.setItem('vitals.mockup', 'on'))
  await page.reload()
  await page.waitForLoadState('domcontentloaded')
  await sleep(800)
  await page.keyboard.press('Escape')
  await sleep(600)
  await page.getByRole('button', { name: 'Vitals (mock-up)' }).click()
  await page.waitForSelector('.vitals-root [data-verdict]')
  // Health's live copy, the loops and the accounts' fresh check take a few seconds; the map a few more.
  await page.waitForFunction(() => document.querySelector('.vitals-root [data-reading]')?.textContent?.includes('as of'), null, { timeout: 30_000 })
  await sleep(9000)

  const shoot = async (name, what) => {
    const file = path.join(OUT, `${name}.png`)
    await page.screenshot({ path: file })
    shots.push({ file, what })
    console.log(file)
  }
  const place = async (p) => {
    await page.getByRole('button', { name: p === 'overlay' ? 'Over the map' : 'Below the map' }).click()
    await sleep(700)
  }
  const sizes = [['860', { width: 860, height: 900 }], ['1080', { width: 1080, height: 900 }], ['1440', { width: 1440, height: 900 }], ['vertical', { width: 1080, height: 1920 }]]
  for (const p of ['overlay', 'below']) {
    await place(p)
    for (const [label, vp] of sizes) {
      await page.setViewportSize(vp)
      await page.evaluate(() => document.querySelector('main')?.scrollTo(0, 0))
      await sleep(1500)
      await shoot(`vitals-${p}-${label}`, `${p === 'overlay' ? 'Column over the map' : 'Column below the map'} at ${label === 'vertical' ? 'the vertical monitor (1080 x 1920)' : `${label} px`}`)
    }
  }
  // Pointing at a row lights its part on the map; tapping it opens the evidence.
  await place('overlay')
  await page.setViewportSize({ width: 1440, height: 900 })
  await sleep(1200)
  const row = page.locator('.vitals-root [data-row^="check:disk:space"]').first()
  const target = (await row.count()) ? row : page.locator('.vitals-root [data-row]').first()
  await target.hover()
  await sleep(1500)
  await shoot('vitals-overlay-1440-pointed', 'Pointing at a row: its part on the map stays lit, the rest dims')
  await target.click()
  await sleep(1200)
  await shoot('vitals-overlay-1440-evidence', 'Tapping a row opens its evidence beside the column')
  // The Accounts card, full width and under 900 px.
  for (const [label, vp] of [['1440', { width: 1440, height: 900 }], ['860', { width: 860, height: 900 }]]) {
    await page.setViewportSize(vp)
    await sleep(800)
    const card = page.locator('[data-card="vitals-accounts"]')
    await card.scrollIntoViewIfNeeded()
    await sleep(500)
    const file = path.join(OUT, `vitals-accounts-${label}.png`)
    await card.screenshot({ path: file })
    shots.push({ file, what: `Accounts card at ${label} px` })
    console.log(file)
  }
  fs.writeFileSync(path.join(OUT, 'shots.json'), JSON.stringify(shots, null, 2))
} catch (err) {
  console.error(`capture failed: ${err?.message || err}`)
  process.exitCode = 1
} finally {
  if (browser) await browser.close().catch(() => {})
  proc.kill('SIGTERM')
  await sleep(1500)
  if (proc.exitCode === null) proc.kill('SIGKILL')
  fs.rmSync(profile, { recursive: true, force: true })
}
