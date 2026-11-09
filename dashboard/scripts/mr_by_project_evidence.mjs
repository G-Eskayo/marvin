// Evidence capture for marvin#848 (MR Review by project, wired into the real tab). Drives the built app against a
// sandbox HOME holding copies of this machine's project catalog, overrides.json (the one place for names) and board
// registry, with the real open PRs of every board repo as the fixed list (MARVIN_MR_FIXTURE, read once through
// bin/gh with the list's own fields). Helper chips come from this machine's real WezTerm tabs. Never the real store,
// webhook or a merge: a stand-in server answers the merge service's side reads with nothing.
// Usage: HOME=<sandbox dir> node mr_by_project_evidence.mjs <out-dir>
import { chromium } from 'playwright-core'
import { spawn, execFileSync } from 'node:child_process'
import { createServer } from 'node:http'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'
import { prListArgs } from '../electron/main/mr_repos.js'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT] = process.argv.slice(2)
const HOME = process.env.HOME
const REAL = os.userInfo().homedir
if (!OUT || !HOME || HOME === REAL || !HOME.includes('sandbox')) {
  console.error('usage: HOME=<a sandbox dir, path containing "sandbox"> node mr_by_project_evidence.mjs <out-dir>')
  process.exit(1)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
fs.mkdirSync(OUT, { recursive: true })

// ---- the sandbox: the catalog, overrides and boards as they are on this machine ----
for (const d of ['catalog', 'boards', 'logs']) fs.mkdirSync(path.join(HOME, '.claude', d), { recursive: true })
for (const f of fs.readdirSync(path.join(REAL, '.claude', 'catalog')).filter((n) => n.endsWith('.json'))) {
  fs.copyFileSync(path.join(REAL, '.claude', 'catalog', f), path.join(HOME, '.claude', 'catalog', f))
}
fs.copyFileSync(path.join(REAL, '.claude', 'boards', 'registry.json'), path.join(HOME, '.claude', 'boards', 'registry.json'))

// ---- the real open PRs, read once ----
const GH = path.join(REAL, '.agents', 'bin', 'gh')
const registry = JSON.parse(fs.readFileSync(path.join(HOME, '.claude', 'boards', 'registry.json'), 'utf8')).boards
const prs = []
for (const b of registry.filter((x) => !x.finishedAt)) {
  try {
    const list = JSON.parse(execFileSync(GH, prListArgs(b.repo), { encoding: 'utf8', maxBuffer: 64 << 20, env: { ...process.env, HOME: REAL } }))
    for (const p of list) prs.push({ ...p, repo: b.repo })
  } catch (e) {
    console.error(`skipped ${b.repo}: ${String(e.message).slice(0, 120)}`)
  }
}
const FIXTURE = path.join(HOME, 'fixture-prs.json')
fs.writeFileSync(FIXTURE, JSON.stringify(prs))
console.log(`${prs.length} open PRs from ${registry.length} boards`)

const server = createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'application/json' })
  res.end(req.url.startsWith('/merge-history') ? JSON.stringify({ merges: [], refusals: [] }) : '{}')
})
const srvPort = await freePort()
await new Promise((r) => server.listen(srvPort, '127.0.0.1', r))

const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const port = await freePort()
const env = { ...captureLaunchEnv(process.env), MARVIN_MR_FIXTURE: FIXTURE,
  MARVIN_MR_WEBHOOK_URL: `http://127.0.0.1:${srvPort}/approve`, MARVIN_MR_LOCAL_WEBHOOK_URL: `http://127.0.0.1:${srvPort}/approve` }
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env, stdio: 'ignore' })
let b
for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page
for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
const shot = async (name, opts = {}) => { await sleep(600); await page.screenshot({ path: path.join(OUT, name), ...opts }); console.log(name) }

try {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.locator('main').waitFor({ timeout: 30000 })
  for (let i = 0; i < 80; i++) {
    if (!(await page.locator('.boot-root').count())) { if (i > 4) break } else await page.keyboard.press('Escape')
    await sleep(300)
  }
  await page.locator('button', { hasText: 'MR Review' }).first().click()
  await page.locator('[data-group]').first().waitFor({ timeout: 30000 })
  await sleep(2500) // projects and helper tabs arrive beside the list

  // 1. Opens on By project: groups with something for you open, the rest collapsed, empty projects dimmed at the end.
  await shot('01-by-project.png')
  // 2. The whole list, down to the empty projects.
  const main = page.locator('main')
  await main.evaluate((el) => { el.style.overflow = 'visible'; el.style.height = 'auto' })
  await shot('02-by-project-full.png', { fullPage: true })
  await main.evaluate((el) => { el.style.overflow = ''; el.style.height = '' })

  // 3. Tapping a project's name collapses it, the same as the arrow (and the choice is remembered).
  const header = page.locator('[data-group] button[aria-expanded="true"]').first()
  const name = await header.locator('span').nth(1).innerText()
  await header.locator('span').nth(1).click()
  await shot('03-tap-name-collapses.png')
  await page.locator('[data-group] button', { hasText: name }).first().locator('span').nth(1).click() // open again

  // 4. All: the same cards, needs you first across every project.
  await main.evaluate((el) => { el.scrollTop = 0 })
  await page.locator('button', { hasText: /^All$/ }).click()
  await shot('04-all.png')

  // 5. Narrow window.
  await page.locator('button', { hasText: /^By project$/ }).click()
  await page.setViewportSize({ width: 860, height: 900 })
  await shot('05-narrow-860.png')
  await page.setViewportSize({ width: 1280, height: 900 })

  // 6. The boards say the same names (Activity).
  await page.locator('button', { hasText: 'Activity' }).first().click()
  await sleep(2500)
  const boards = page.locator('h1', { hasText: 'Project Boards' }).first()
  await boards.scrollIntoViewIfNeeded()
  const box = await boards.boundingBox()
  await shot('06-activity-same-names.png', { clip: { x: 0, y: box.y - 16, width: 1280, height: Math.min(560, 900 - box.y + 16) } })
} finally {
  await b?.close().catch(() => {})
  proc.kill()
  server.close()
}
