// Screenshots of the #872 plan-usage + throttle-switch mock-up: each scene in Workshop (closed and opened), the Vitals
// alternative, and narrow widths (the owner views mock-ups narrow on the Mini).
//
//   node docs/design/872-usage-toggle/shoot.mjs <outDir>
//
// Needs Google Chrome; playwright-core comes from ~/.agents/dashboard/node_modules (no install in a worktree).
import { createRequire } from 'module'
import { mkdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { fileURLToPath, pathToFileURL } from 'url'

const here = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(path.join(homedir(), '.agents/dashboard/package.json'))
const { chromium } = require('playwright-core')
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const out = path.resolve(process.argv[2] || path.join(here, 'shots'))
mkdirSync(out, { recursive: true })

// [scene, place, open, width]
const SHOTS = [
  ['clear', 'workshop', 0, 1180], ['clear', 'workshop', 1, 1180], ['soft', 'workshop', 1, 860], ['warn', 'workshop', 1, 1180],
  ['hard', 'workshop', 1, 860], ['off', 'workshop', 0, 860], ['nodata', 'workshop', 1, 860], ['stale', 'workshop', 1, 1180],
  ['soft', 'vitals', 1, 860], ['hard', 'workshop', 1, 390]
]
const browser = await chromium.launch({ executablePath: CHROME, headless: true })
try {
  for (const [scene, place, open, width] of SHOTS) {
    const page = await browser.newPage({ viewport: { width, height: 500 }, deviceScaleFactor: 2 })
    await page.goto(pathToFileURL(path.join(here, 'index.html')).href + `#scene=${scene}&place=${place}&open=${open}`)
    await page.waitForFunction(() => window.__ready)
    await page.evaluate(() => document.fonts.ready)
    const file = path.join(out, `872-${scene}-${place}${open ? '-open' : ''}-${width}.png`)
    await page.screenshot({ path: file, fullPage: true })
    await page.close()
    console.log(file)
  }
} finally {
  await browser.close()
}
