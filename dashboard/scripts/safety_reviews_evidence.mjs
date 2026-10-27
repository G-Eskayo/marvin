// Evidence capture for Health ▸ Safety reviews (2026-10-26). Drives the built app in its own Electron (own
// user-data-dir, own CDP port) against a sandbox HOME holding a FAKE quarantine.md written here, never the owner's
// running MARVIN.app or ~/.claude. The sandbox's ~/.agents links only the venv and this checkout's skills, so the card
// reads and answers through the real process_quarantine_reviews.py.
// Usage: HOME=<sandbox dir, path containing "sandbox"> node safety_reviews_evidence.mjs <real venv dir> <out-dir>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [VENV, OUT] = process.argv.slice(2)
const HOME = process.env.HOME
if (!VENV || !OUT || !HOME || !HOME.includes('sandbox')) {
  console.error('usage: HOME=<sandbox dir> node safety_reviews_evidence.mjs <venv-dir> <out-dir>')
  process.exit(1)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ---- sandbox ----
fs.mkdirSync(path.join(HOME, '.agents'), { recursive: true })
fs.mkdirSync(path.join(HOME, '.claude'), { recursive: true })
for (const [name, target] of [['venv', VENV], ['skills', path.resolve(APP, '..', 'skills')]]) {
  const link = path.join(HOME, '.agents', name)
  if (!fs.existsSync(link)) fs.symlinkSync(target, link)
}
const quote = (text) => text.split('\n').map((l) => `> ${l}`).join('\n')
const entry = (date, loop, score, body, reason) =>
  `\n---\n## ${date} — ${loop} [SAFETY, score ${score}, tau 0.30]\n${quote(body)}\n\n${reason ? `Flagged reason: ${reason}\n\n` : ''}` +
  '- [ ] approve (ships as-is)\n- [ ] modify: ____________\n- [ ] deny\n'
const entries = [
  entry('2026-10-24', 'research_colony', '0.35',
    '## Directly Relevant\n\n**Selective human audits for autonomous loops** — a method for choosing which outputs get a human audit, ' +
    'ranked by how much a label would move the threshold. Worth a read before the next calibration pass. [arxiv](http://arxiv.org/abs/0000.00000)\n\n' +
    '## Worth Watching\n\n- Fixture item two: a benchmark of small judges against large ones.\n- Fixture item three: <script>alert("entry text is shown as text")</script>\n' +
    '- Fixture item four: a [javascript: link](javascript:alert(1)) stays plain text.\n\n> A quoted note from the source.\n\n' +
    '| Source | Items |\n|---|---|\n| arXiv | 12 |\n| GitHub | 7 |',
    'possible unsupported claim'),
  entry('2026-10-25', 'daily_digest', '0.42', '## Feature Combinations\n\nFixture digest text for the second card.', ''),
  ...Array.from({ length: 10 }, (_, i) => entry('2026-10-26', 'self_improve', '0.31', `Fixture retrospective line ${i + 3}.`, 'flagged before landing'))
]
fs.writeFileSync(path.join(HOME, '.claude', 'quarantine.md'), '# Quarantine\n\nArtifacts flagged by the safety monitor, awaiting review.\n' + entries.join(''))

// ---- capture ----
fs.mkdirSync(OUT, { recursive: true })
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const port = await freePort()
const env = captureLaunchEnv({ ...process.env, MARVIN_MR_WEBHOOK_URL: 'http://127.0.0.1:9/approve' })
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`, `--user-data-dir=${path.join(HOME, 'electron-data')}`], { env, stdio: 'ignore' })
let b
try {
  for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
  let page
  for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
  page.on('console', (m) => m.type() === 'error' && console.error('[page]', m.text()))
  const click = (tag, text) => page.evaluate(([tag, text]) => {
    const el = [...document.querySelectorAll(tag)].find((e) => e.textContent.trim().startsWith(text))
    if (!el) throw new Error(`no ${tag} "${text}"`)
    el.click()
  }, [tag, text])
  await page.setViewportSize({ width: 1280, height: 1000 })
  await sleep(6000)
  await page.keyboard.press('Escape') // skips the boot sequence
  await sleep(800)
  await click('button', 'Health')
  await page.waitForSelector('button:has-text("Safety reviews (")', { timeout: 30000 })
  await click('button', 'Safety reviews')
  await page.waitForSelector('[data-review-id]', { timeout: 20000 })
  await sleep(800)
  const view = page.locator('section').filter({ has: page.locator('[data-review-id]') }).first()
  const tabs = async (file) => {
    const box = await view.boundingBox()
    const top = await page.locator('button:has-text("Safety reviews (")').boundingBox()
    await page.screenshot({ path: `${OUT}/${file}`, clip: { x: 0, y: Math.max(0, top.y - 12), width: page.viewportSize().width, height: box.y + box.height - top.y + 28 } })
  }
  await tabs('safety-reviews-card.png')
  await click('button', 'Show full item')
  await sleep(500)
  await tabs('safety-reviews-expanded.png')
  await click('button', 'Show less')
  await click('button', 'Fix it')
  await page.locator('textarea').fill('Drop the second claim; it has no source.')
  await sleep(400)
  await tabs('safety-reviews-fix-it.png')
  await page.setViewportSize({ width: 820, height: 1000 })
  await sleep(1000)
  await tabs('safety-reviews-820px.png')
  await page.setViewportSize({ width: 1280, height: 1000 })
  await click('button', 'Submit')
  await page.waitForSelector('text=Safety reviews (2 of 12)', { timeout: 20000 })
  await sleep(600)
  await tabs('safety-reviews-next-card.png')
  const rows = fs.readFileSync(path.join(HOME, '.claude', 'safety-monitor', 'calibration.jsonl'), 'utf8')
  console.log('label recorded:', rows.trim())
  console.log('shots in', OUT)
} finally {
  await b?.close().catch(() => {})
  proc.kill('SIGTERM')
  await sleep(1500)
  if (proc.exitCode === null) proc.kill('SIGKILL')
}
