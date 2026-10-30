// Screenshots of the #847 Health card mock-up: every scene's grid, the drill-down for the scenes that differ, and a
// narrow window (the owner views mock-ups narrow on the Mini).
//
//   node docs/design/847-health-card/shoot.mjs <outDir>
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

const SHOTS = [
  ['today', 'grid', 1180], ['today', 'detail', 1180],
  ['quiet', 'grid', 1180], ['waiting', 'grid', 1180], ['helper', 'detail', 1180], ['notice', 'detail', 1180],
  ['incident', 'grid', 1180], ['incident', 'detail', 1180], ['needsyou', 'grid', 1180], ['needsyou', 'detail', 1180],
  ['away', 'grid', 1180], ['today', 'detail', 820],
]
const browser = await chromium.launch({ executablePath: CHROME, headless: true })
try {
  for (const [scene, view, width] of SHOTS) {
    const page = await browser.newPage({ viewport: { width, height: 400 }, deviceScaleFactor: 2 })
    await page.goto(pathToFileURL(path.join(here, 'index.html')).href + `?scene=${scene}&view=${view}`)
    await page.waitForFunction(() => window.__ready)
    const file = path.join(out, `847-${scene}-${view}${width < 900 ? '-narrow' : ''}.png`)
    await page.screenshot({ path: file, fullPage: true })
    await page.close()
    console.log(file)
  }
} finally {
  await browser.close()
}
