// Evidence capture for marvin#565 (Docs tab: stop calling GitHub on every click for projects without a local clone).
// Drives the BUILT app (real preload/IPC) against a sandbox HOME (never the real ~/.claude), attaches over CDP, times
// opening a GitHub-only project and its files, and counts every network call the app makes while doing it:
//   - `gh` calls, logged by a PATH shim (the sandbox .zshrc puts it first, and the app adopts the login-shell PATH);
//   - main-process fetch calls, logged by a --require'd counter (NODE_OPTIONS).
// Both append to EVIDENCE_NET_LOG. Usage:
//   npm run build && HOME=<sandbox> EVIDENCE_NET_LOG=<file> NODE_OPTIONS="--require <counter.cjs>" \
//     node scripts/docs_saved_evidence.mjs <out-dir> <project-name>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT, PROJECT = 'paper-dive', OTHER = 'marvin'] = process.argv.slice(2)
const HOME = process.env.HOME
const LOG = process.env.EVIDENCE_NET_LOG
if (!OUT || HOME === '/Users/gileskayo' || !LOG) {
  console.error('usage: HOME=<sandbox> EVIDENCE_NET_LOG=<file> node docs_saved_evidence.mjs <out-dir> [project] [other-project]')
  process.exit(1)
}
fs.mkdirSync(OUT, { recursive: true })
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
let b
for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page
for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
await page.setViewportSize({ width: 1400, height: 980 })
await sleep(4000)
// The boot sequence overlays the app until any key skips it.
await page.keyboard.press('Escape')
for (let i = 0; i < 40 && (await page.evaluate(() => !!document.querySelector('[data-b="sky"]'))); i++) await sleep(250)
await sleep(3000)

const netLines = () => (fs.existsSync(LOG) ? fs.readFileSync(LOG, 'utf8').split('\n').filter(Boolean) : [])
const docsNet = (lines) => lines.filter((l) => / gh .*repos\/G-Eskayo\/\S+\/(contents|git)/.test(l) || /git\/trees/.test(l))
const results = []
const report = (name, value) => { results.push({ name, value }); console.log(`${name}: ${typeof value === 'string' ? value : JSON.stringify(value)}`) }

// Click a project or doc button by its text, then wait (in the page, frame by frame) until the main pane's source line
// starts with `source` and a tree button reads `item`; returns ms from the click to the frame after (a paint has
// happened by then). The source line tells the new project's tree from the one it replaced.
const clickAndTime = (clickText, source, item) =>
  page.evaluate(async ([ct, src, it]) => {
    const el = [...document.querySelectorAll('button')].find((e) => e.textContent.trim().replace(/[●\s]+$/, '') === ct)
    if (!el) throw new Error(`no button "${ct}"`)
    const t0 = performance.now()
    el.click()
    await new Promise((r) => setTimeout(r, 0)) // let React drop the old tree first
    return await new Promise((resolve, reject) => {
      const stop = setTimeout(() => reject(new Error(`"${src}" + "${it}" never appeared`)), 10000)
      const tick = () => {
        const srcOk = [...document.querySelectorAll('p')].some((p) => p.textContent.startsWith(src))
        const itemOk = [...document.querySelectorAll('.w-56 button')].some((b) => b.textContent.trim() === it)
        if (srcOk && itemOk) requestAnimationFrame(() => { clearTimeout(stop); resolve(Math.round((performance.now() - t0) * 10) / 10) })
        else requestAnimationFrame(tick)
      }
      tick()
    })
  }, [clickText, source, item])
const sourceLine = () => page.evaluate(() => [...document.querySelectorAll('p')].find((p) => p.textContent.startsWith('Reading GitHub'))?.textContent || null)
const waitSource = async (re, ms = 15000) => { for (let t = 0; t < ms; t += 100) { const s = await sourceLine(); if (s && re.test(s)) return s; await sleep(100) } return await sourceLine() }

try {
  await page.evaluate(() => [...document.querySelectorAll('button')].find((e) => e.textContent.trim() === 'Docs').click())
  await sleep(1500)

  // 1. First open of the GitHub-only project: the saved copy (seeded from the search index) paints at once, then the
  // one conditional request runs. EVIDENCE_NET_DELAY_MS holds it back so the "checking…" state can be shot.
  let mark = netLines().length
  const firstPaint = await clickAndTime(PROJECT, 'Reading GitHub', 'README.md')
  report('first open: tree painted from saved state (ms)', firstPaint)
  report('first open: source line right after paint', await sourceLine())
  await page.screenshot({ path: `${OUT}/ticket-565-github-checking.png` })
  report('first open: settled', await waitSource(/up to date|could not check/))
  await sleep(1200)
  await page.screenshot({ path: `${OUT}/ticket-565-github-up-to-date.png` })
  const firstNet = docsNet(netLines().slice(mark))
  report('first open: network calls', firstNet.length)
  firstNet.forEach((l) => console.log('   ', l))

  // 2. Clicks inside the project: every doc in the tree, ten rounds. Zero network calls expected.
  const items = await page.evaluate(() => [...document.querySelectorAll('.w-56 button span.truncate')].map((s) => s.textContent).filter((t) => t !== 'Project card'))
  report('docs in the tree after the check', items)
  mark = netLines().length
  const fileTimes = []
  for (let round = 0; round < 10; round++) {
    for (const label of items) {
      const ms = await page.evaluate(async (lbl) => {
        const el = [...document.querySelectorAll('.w-56 button')].find((e) => e.textContent.trim() === lbl)
        const t0 = performance.now()
        el.click()
        return await new Promise((resolve) => {
          const tick = () => {
            const body = document.querySelector('.max-w-3xl')
            if (body && !document.body.innerText.includes('Loading…') && body.querySelector('h1,h2,h3,p,pre,li')) requestAnimationFrame(() => resolve(performance.now() - t0))
            else requestAnimationFrame(tick)
          }
          requestAnimationFrame(tick)
        })
      }, label)
      fileTimes.push(ms)
    }
  }
  fileTimes.sort((a, b) => a - b)
  const pct = (p) => Math.round(fileTimes[Math.min(fileTimes.length - 1, Math.floor((p / 100) * fileTimes.length))] * 10) / 10
  report(`file opens (${fileTimes.length}): median / p95 / max (ms)`, `${pct(50)} / ${pct(95)} / ${Math.round(fileTimes.at(-1) * 10) / 10}`)
  report('file opens: network calls', docsNet(netLines().slice(mark)).length)
  await page.screenshot({ path: `${OUT}/ticket-565-github-file-open.png` })

  // 3. Re-open (another project, then back): one conditional request, answered 304.
  await clickAndTime(OTHER, 'Reading local clone', 'Project card')
  await sleep(800)
  mark = netLines().length
  const reopen = await clickAndTime(PROJECT, 'Reading GitHub', 'README.md')
  report('re-open: tree painted from saved state (ms)', reopen)
  report('re-open: settled', await waitSource(/up to date|could not check/))
  await sleep(500)
  const re = docsNet(netLines().slice(mark))
  report('re-open: network calls', re.length)
  re.forEach((l) => console.log('   ', l))
} catch (err) {
  console.error('FAILED', err)
  process.exitCode = 1
} finally {
  fs.writeFileSync(path.join(OUT, 'ticket-565-evidence.json'), JSON.stringify(results, null, 2))
  await b?.close().catch(() => {})
  proc.kill('SIGTERM')
  await sleep(1500)
  try { proc.kill('SIGKILL') } catch {}
}
