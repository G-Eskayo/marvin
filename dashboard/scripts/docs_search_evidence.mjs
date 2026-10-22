// Evidence for the Docs search fix: drives the BUILT app against a sandbox HOME (a clone of the real catalog, outbox
// and saved copies; never the real ~/.claude), attaches over CDP, types each real query into the Docs search and
// records what the results pane shows. Usage: npm run build && HOME=<sandbox> MARVIN_VAR_DIR=<sandbox var> \
//   node scripts/docs_search_evidence.mjs <out-dir> <label> '<json array of queries>' [shot-query]
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT, LABEL, QUERIES, SHOT] = process.argv.slice(2)
if (!OUT || process.env.HOME === '/Users/gileskayo' || !QUERIES) {
  console.error('usage: HOME=<sandbox> node docs_search_evidence.mjs <out-dir> <label> <queries-json> [shot-query]')
  process.exit(1)
}
fs.mkdirSync(OUT, { recursive: true })
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`, `--user-data-dir=${path.join(process.env.HOME, 'electron-user-data')}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
try {
  let b
  for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
  let page
  for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
  await page.setViewportSize({ width: 1400, height: 980 })
  await sleep(3000)
  await page.keyboard.press('Escape') // skip the boot sequence
  for (let i = 0; i < 40 && (await page.evaluate(() => !!document.querySelector('[data-b="sky"]'))); i++) await sleep(250)
  await sleep(1500)
  await page.evaluate(() => [...document.querySelectorAll('button')].find((e) => e.textContent.trim() === 'Docs')?.click())
  await sleep(1500)
  const input = page.locator('input[placeholder^="Search all docs"]')
  const rows = []
  for (const q of JSON.parse(QUERIES)) {
    await input.fill('')
    await input.fill(q)
    // Wait for the count line ("N results for “q”"); Spotlight's file section is not part of the docs search.
    let line = null
    for (let i = 0; i < 80 && !line; i++) {
      line = await page.evaluate((qq) => [...document.querySelectorAll('p')].map((p) => p.textContent).find((t) => t.includes(`for “${qq}”`)) || null, q)
      if (!line) await sleep(100)
    }
    const top = await page.evaluate(() => [...document.querySelectorAll('li > button.rounded-lg')].filter((b) => b.querySelector('p')).slice(0, 3).map((b) => [...b.querySelectorAll('p')].slice(0, 2).map((p) => p.textContent.trim()).join(' — ')))
    rows.push({ q, line, top })
    console.log(JSON.stringify({ q, line, top }))
    if (q === SHOT) { await page.mouse.move(5, 975); await sleep(600); await page.screenshot({ path: `${OUT}/docs-search-${LABEL}.png` }) }
  }
  fs.writeFileSync(`${OUT}/docs-search-${LABEL}.json`, JSON.stringify(rows, null, 2))
} finally {
  proc.kill('SIGKILL') // a plain SIGTERM left the app running (2026-10-22)
}
