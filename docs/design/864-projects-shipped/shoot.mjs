// Screenshots of the #864 Workshop Projects and Shipped mock-up, at 1440, 860 and phone width (the owner views
// mock-ups narrow on the Mini).
//
//   node docs/design/864-projects-shipped/shoot.mjs <outDir>
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

// [name, hash, width, after (ms, for motion)]
const SHOTS = [
  ['01-projects-1440', 'view=projects', 1440],
  ['02-projects-860', 'view=projects', 860],
  ['03-projects-935-words-groups-860', 'view=projects&words=935&lanes=groups&tags=0', 860],
  ['04-projects-burnup-1440', 'view=projects&macro=burnup&tags=0', 1440],
  ['05-projects-edges-860', 'view=projects&scene=edges&tags=0', 860],
  ['06-board-1440', 'view=projects&board=marvin', 1440],
  ['07-shipped-i4-1440', 'view=shipped&ship=i4&arrive=1', 1440, 1600],
  ['08-shipped-i4-860', 'view=shipped&ship=i4', 860],
  ['09-shipped-today-860', 'view=shipped&ship=today', 860],
  ['10-now-throttle-860', 'view=now', 860],
  ['11-gone-1440', 'view=gone', 1440],
  ['12-gone-390', 'view=gone', 390],
  ['13-projects-390', 'view=projects&tags=0', 390],
  ['14-shipped-390', 'view=shipped', 390]
]
const browser = await chromium.launch({ executablePath: CHROME, headless: true })
try {
  for (const [name, hash, width, wait = 0] of SHOTS) {
    const page = await browser.newPage({ viewport: { width, height: 900 }, deviceScaleFactor: 2 })
    await page.goto(pathToFileURL(path.join(here, 'index.html')).href + `#${hash}`)
    await page.waitForFunction(() => window.__ready)
    await page.evaluate(() => document.fonts.ready)
    if (wait) await page.waitForTimeout(wait)
    const scroll = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    if (scroll > 0) console.warn(`${name}: scrolls sideways by ${scroll}px`)
    const file = path.join(out, `${name}.png`)
    await page.screenshot({ path: file, fullPage: true })
    await page.close()
    console.log(file)
  }
} finally {
  await browser.close()
}
