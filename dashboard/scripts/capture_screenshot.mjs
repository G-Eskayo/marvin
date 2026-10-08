// Single-shot dev-environment evidence capture for the MR pipeline
// (G-Eskayo/marvin#77, ADR 0024). Launches this app's built Electron
// by passing it to Playwright's chromium.launch (treating Electron's
// binary as a standard Chromium executable), finds the real UI window
// (not devtools, not a splash screen), screenshots it, and quits.
//
// Usage: node capture_screenshot.mjs <output-path>
// Assumes `npm run build` has already produced ./out/ in this directory
// (the caller is responsible for that -- this script only launches and
// shoots, it doesn't build).
import { chromium } from 'playwright-core'
import path from 'node:path'
import fs from 'node:fs'
import { selectContentPage } from '../src/lib/screenshot_capture.js'

const APP_DIR = path.resolve(import.meta.dirname, '..')
const outputPath = process.argv[2]

if (!outputPath) {
  console.error('usage: node capture_screenshot.mjs <output-path>')
  process.exit(1)
}

const electronBin =
  process.platform === 'darwin'
    ? path.join(APP_DIR, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
    : path.join(APP_DIR, 'node_modules/electron/dist/electron')

if (!fs.existsSync(path.join(APP_DIR, 'out', 'main', 'index.js'))) {
  console.error(`no build output at ${APP_DIR}/out -- run "npm run build" first`)
  process.exit(1)
}

let browser = null

try {
  // Use Playwright's chromium.launch to start Electron as a generic Chromium executable.
  // This avoids the experimental _electron.launch API which has version-compat issues
  // with Electron 30.5.1. Playwright owns spawn, stderr-parsing, and the DevTools WS handshake.
  browser = await chromium.launch({
    executablePath: electronBin,
    args: [APP_DIR, '--no-sandbox'],
  })

  // Poll for a real content page (not devtools://) up to ~10s
  let page = null
  const deadline = Date.now() + 10_000
  while (Date.now() < deadline) {
    const contexts = browser.contexts()
    if (contexts.length > 0) {
      const pages = contexts[0].pages()
      page = selectContentPage(pages)
      if (page) break
    }
    await new Promise((r) => setTimeout(r, 200))
  }

  if (!page) {
    throw new Error('no real content window appeared within 10s')
  }

  await page.waitForLoadState('domcontentloaded')
  fs.mkdirSync(path.dirname(outputPath), { recursive: true })
  await page.screenshot({ path: outputPath })
  console.log(outputPath)
} catch (err) {
  console.error(err.message || String(err))
  process.exit(1)
} finally {
  // Close the browser, which also closes the Electron process entirely
  if (browser) {
    await browser.close().catch(() => {})
  }
}
