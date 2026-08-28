// Single-shot dev-environment evidence capture for the MR pipeline
// (G-Eskayo/marvin#77, ADR 0024). Launches this app's built Electron
// output, waits for the real UI window (not devtools, not a splash
// screen), screenshots it, and quits -- no REPL, since this runs
// unattended from evidence_capture.py rather than being driven
// interactively. Adapted from the `run` skill's Electron driver pattern
// (~/.agents/skills/run when wired, or the bundled run skill's
// examples/electron.md) -- same _electron.launch/windows()/screenshot
// shape, collapsed to one deterministic sequence instead of a
// stdin-driven command loop.
//
// Usage: node capture_screenshot.mjs <output-path>
// Assumes `npm run build` has already produced ./out/ in this directory
// (the caller is responsible for that -- this script only launches and
// shoots, it doesn't build).
import { _electron as electron } from 'playwright-core'
import path from 'node:path'
import fs from 'node:fs'

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

let app
try {
  app = await electron.launch({
    executablePath: electronBin,
    args: ['--no-sandbox', APP_DIR],
    timeout: 30_000
  })

  // Electron has no clean "loaded" signal -- poll for a real content
  // window (not devtools://) rather than a blind sleep, up to ~10s.
  let page = null
  const deadline = Date.now() + 10_000
  while (Date.now() < deadline) {
    page = app.windows().find((w) => !w.url().startsWith('devtools://'))
    if (page) break
    await new Promise((r) => setTimeout(r, 200))
  }
  if (!page) {
    throw new Error('no real content window appeared within 10s')
  }

  await page.waitForLoadState('domcontentloaded')
  fs.mkdirSync(path.dirname(outputPath), { recursive: true })
  await page.screenshot({ path: outputPath })
  console.log(outputPath)
} finally {
  if (app) await app.close().catch(() => {})
}
