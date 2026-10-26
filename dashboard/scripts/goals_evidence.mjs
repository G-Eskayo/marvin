// Evidence capture for project goals (board top + Activity ▸ Projects, 2026-10-26). Drives the built app in its own
// Electron (own user-data-dir, own CDP port) against a sandbox HOME, never Gil's running MARVIN.app or his ~/.claude:
//   - the real goals: MARVIN_INSTANCE_DIR points at a sandbox copy of the instance's config/projects;
//   - the real board registry, copied in;
//   - a fake `gh` on the sandbox PATH that answers fixture tickets (a held ticket, a needs-you ticket) and no PRs;
//   - a saved Merged-view list with three Seal Speak merges this week; the merge server URL points nowhere.
// Usage: HOME=<sandbox dir, path containing "sandbox"> node goals_evidence.mjs <profiles-dir> <registry.json> <out-dir>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [PROFILES, REGISTRY, OUT] = process.argv.slice(2)
const HOME = process.env.HOME
if (!PROFILES || !REGISTRY || !OUT || !HOME || !HOME.includes('sandbox')) {
  console.error('usage: HOME=<sandbox dir> node goals_evidence.mjs <profiles-dir> <registry.json> <out-dir>')
  process.exit(1)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const put = (p, text) => (fs.mkdirSync(path.dirname(p), { recursive: true }), fs.writeFileSync(p, text))

// ---- sandbox ----
const instance = path.join(HOME, 'instance')
fs.cpSync(PROFILES, path.join(instance, 'config', 'projects'), { recursive: true })
fs.mkdirSync(path.join(HOME, '.claude', 'boards'), { recursive: true })
fs.copyFileSync(REGISTRY, path.join(HOME, '.claude', 'boards', 'registry.json'))
const now = Date.now()
const day = (d) => new Date(now - d * 86_400_000).toISOString()
const issue = (number, title, labels) => ({ number, title, state: 'OPEN', stateReason: null, labels: labels.map((name) => ({ name })), body: '', url: `https://github.com/x/y/issues/${number}`, createdAt: day(3), updatedAt: day(1), closedAt: null })
const fixtures = {
  'G-Eskayo/marvin': [issue(901, 'Fixture: needs a person', ['ready-for-human'])],
  'G-Eskayo/portfolio-website-updater': [issue(902, 'Fixture: on hold', ['hold'])]
}
for (const [repo, list] of Object.entries(fixtures)) put(path.join(HOME, 'gh-fixtures', `${repo.replace('/', '__')}.json`), JSON.stringify(list))
put(path.join(HOME, '.claude', 'logs', 'mr-history.json'), JSON.stringify({
  updatedAt: now,
  merged: [1, 2, 3].map((n) => ({ url: `https://github.com/G-Eskayo/clarity-captions/pull/${900 + n}`, number: 900 + n, title: `Fixture merge ${n}`, repo: 'G-Eskayo/clarity-captions', mergedAt: day(n) })),
  history: { merges: [], refusals: [] },
  open: []
}))
// gh: open issues from the fixtures, everything else empty. Arguments: issue list --repo <r> --state open ...
put(path.join(HOME, '.agents', 'bin', 'gh'), `#!/bin/sh
repo=""; state=""; prev=""
for a in "$@"; do [ "$prev" = "--repo" ] && repo="$a"; [ "$prev" = "--state" ] && state="$a"; prev="$a"; done
f="$HOME/gh-fixtures/$(echo "$repo" | sed 's#/#__#').json"
if [ "$1" = "issue" ] && [ "$2" = "list" ] && [ "$state" = "open" ] && [ -f "$f" ]; then cat "$f"; exit 0; fi
case "$1" in auth) echo fake-token; exit 0;; esac
echo '[]'
`)
fs.chmodSync(path.join(HOME, '.agents', 'bin', 'gh'), 0o755)
put(path.join(HOME, '.zshrc'), `export PATH="$HOME/.agents/bin:$PATH"\n`)

// ---- capture ----
fs.mkdirSync(OUT, { recursive: true })
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const port = await freePort()
const env = captureLaunchEnv({ ...process.env, PATH: `${HOME}/.agents/bin:${process.env.PATH}`, MARVIN_INSTANCE_DIR: instance, MARVIN_MR_WEBHOOK_URL: 'http://127.0.0.1:9/approve' })
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`, `--user-data-dir=${path.join(HOME, 'electron-data')}`], { env, stdio: 'ignore' })
let b
try {
  for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
  let page
  for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
  const click = (tag, text) => page.evaluate(([tag, text]) => {
    const el = [...document.querySelectorAll(tag)].find((e) => e.textContent.trim().startsWith(text))
    if (!el) throw new Error(`no ${tag} "${text}"`)
    el.click()
  }, [tag, text])
  await page.setViewportSize({ width: 1280, height: 1000 })
  await sleep(6000)
  await page.keyboard.press('Escape') // skips the boot sequence
  await sleep(800)
  await click('button', 'Activity')
  page.on('console', (m) => m.type() === 'error' && console.error('[page]', m.text()))
  await page.waitForSelector('text=parked or done', { timeout: 30000 }).catch(async (e) => {
    await page.screenshot({ path: `${OUT}/debug-activity.png` })
    console.error('progress:', await page.evaluate(() => window.api.activity.progress().then((d) => JSON.stringify(d).slice(0, 400), (e) => String(e))))
    throw e
  })
  await sleep(2500)
  const projects = page.locator('h2:text-is("Projects")').locator('..')
  await projects.screenshot({ path: `${OUT}/goals-activity-projects.png` })
  await click('button', '▸')
  await sleep(600)
  await projects.screenshot({ path: `${OUT}/goals-activity-parked-expanded.png` })
  await click('button', '▾')
  await sleep(400)
  await page.setViewportSize({ width: 820, height: 1000 })
  await sleep(1000)
  await projects.screenshot({ path: `${OUT}/goals-activity-820px.png` })
  await page.setViewportSize({ width: 1280, height: 1000 })
  await sleep(600)
  await click('button', 'clarity-captions')
  await page.waitForSelector('text=Goal:', { timeout: 20000 })
  await sleep(2000)
  // The board's top: from the project name down past the goal to the column headers (the sandbox's own error banners
  // above it, from missing python, are not part of this change).
  const boardTop = async (file, width) => {
    const top = await page.locator('h2').filter({ hasText: 'clarity-captions' }).first().boundingBox()
    await page.screenshot({ path: `${OUT}/${file}`, clip: { x: 0, y: Math.max(0, top.y - 16), width, height: 300 } })
  }
  await boardTop('goals-board-top-seal-speak.png', 1280)
  await page.setViewportSize({ width: 820, height: 1000 })
  await sleep(1000)
  await boardTop('goals-board-top-820px.png', 820)
  console.log('shots in', OUT)
} finally {
  await b?.close().catch(() => {})
  proc.kill('SIGTERM')
  await sleep(1500)
  if (proc.exitCode === null) proc.kill('SIGKILL')
}
