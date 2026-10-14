// Single-shot dev-environment evidence capture for the MR pipeline (G-Eskayo/marvin#77, ADR 0024): launches this
// app's built Electron, screenshots the real UI window, and quits. Since marvin#421 it starts Electron itself and
// attaches over CDP (src/lib/cdp_capture.js): Playwright's chromium.launch rejected Electron's app-dir argument
// ("Arguments can not specify page to be opened"), so UI PRs had no screenshots and were refused.
//
// Usage: node capture_screenshot.mjs <output-path>
// Assumes `npm run build` has already produced ./out/ in this directory.
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { captureViaCdp } from '../src/lib/cdp_capture.js'

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
fs.mkdirSync(path.dirname(outputPath), { recursive: true })
const result = await captureViaCdp({
  electronBin, appDir: APP_DIR, env: captureLaunchEnv(process.env), outputPath, chromium, spawn,
  viewport: { width: 1280, height: 900 }
})
if (!result.ok) {
  console.error(`screenshot capture failed: ${result.error}`)
  process.exit(1)
}
console.log(result.path)
