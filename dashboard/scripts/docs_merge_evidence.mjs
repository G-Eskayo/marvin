// Evidence capture for marvin#570 (Docs: fold the Files tab into Docs). Drives the BUILT app against a sandbox HOME
// (never the real ~/.claude: its outbox is a copy), attaches over CDP, shoots the mock-up states, times the speed
// budget and counts every network call the app makes while doing it (gh via a PATH shim, main-process fetch via a
// --require'd counter, both appending to EVIDENCE_NET_LOG; see docs_saved_evidence.mjs from #565).
// Usage: npm run build && HOME=<sandbox> EVIDENCE_NET_LOG=<file> NODE_OPTIONS="--require <counter.cjs>" \
//          node scripts/docs_merge_evidence.mjs <out-dir> [--warm]
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT, flag] = process.argv.slice(2)
const WARM = flag === '--warm'
const HOME = process.env.HOME
const LOG = process.env.EVIDENCE_NET_LOG
if (!OUT || HOME === '/Users/gileskayo' || !LOG) {
  console.error('usage: HOME=<sandbox> EVIDENCE_NET_LOG=<file> node docs_merge_evidence.mjs <out-dir> [--warm]')
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
await sleep(3000)
await page.keyboard.press('Escape') // skip the boot sequence
for (let i = 0; i < 40 && (await page.evaluate(() => !!document.querySelector('[data-b="sky"]'))); i++) await sleep(250)
await sleep(2500)

const netLines = () => (fs.existsSync(LOG) ? fs.readFileSync(LOG, 'utf8').split('\n').filter(Boolean) : [])
const isDocsNet = (l) => / gh .*repos\/G-Eskayo\/\S+\/(contents|git)/.test(l) || /git\/trees/.test(l) || / gh (issue|pr) view/.test(l)
const results = {}
const report = (name, value) => { results[name] = value; console.log(`${name}: ${typeof value === 'string' ? value : JSON.stringify(value)}`) }
const shot = async (name) => { await page.mouse.move(5, 975); await sleep(700); await page.screenshot({ path: `${OUT}/ticket-570-${name}.png` }); console.log('shot', name) }

// Click the first element matching `sel` whose trimmed text (dots and counts stripped) starts with `text`, then wait
// frame by frame until `until` (a page-side predicate source) is true; returns ms from the click to the frame after.
const clickTimed = (sel, text, until, exact = false) =>
  page.evaluate(async ([s, t, u, ex]) => {
    const norm = (e) => e.textContent.trim().replace(/[●▸▾]/g, '').trim()
    const el = [...document.querySelectorAll(s)].find((e) => (ex ? norm(e) === t : norm(e).startsWith(t)))
    if (!el) throw new Error(`no ${s} "${t}"`)
    const pred = new Function(`return (${u})`)
    const t0 = performance.now()
    el.click()
    await new Promise((r) => setTimeout(r, 0))
    return await new Promise((resolve, reject) => {
      const stop = setTimeout(() => reject(new Error(`timed out after clicking "${t}"`)), 15000)
      const tick = () => {
        let ok = false
        try { ok = pred() } catch { ok = false }
        if (ok) requestAnimationFrame(() => { clearTimeout(stop); resolve(Math.round((performance.now() - t0) * 10) / 10) })
        else requestAnimationFrame(tick)
      }
      tick()
    })
  }, [sel, text, until, exact])
const click = (sel, text, exact = false) => page.evaluate(([s, t, ex]) => {
  const norm = (e) => e.textContent.trim().replace(/[●▸▾]/g, '').trim()
  const el = [...document.querySelectorAll(s)].find((e) => (ex ? norm(e) === t : norm(e).startsWith(t)))
  if (!el) throw new Error(`no ${s} "${t}"`)
  el.click()
}, [sel, text, exact])
// Expand a tree folder (and select it) only when it is collapsed, so a second call never closes it.
const expand = (name) => page.evaluate((n) => {
  const el = [...document.querySelectorAll('.w-72 button')].find((e) => e.textContent.replace(/[●▸▾]/g, '').trim().startsWith(n))
  if (!el) throw new Error(`no folder "${n}"`)
  if (el.textContent.trim().startsWith('▸')) el.click()
}, name)
const chip = (k) => page.click(`[data-chip="${k.toLowerCase()}"]`)
const clearChips = async () => {
  for (const k of ['Docs', 'Decisions', 'Deliverables']) {
    const on = await page.evaluate((t) => document.querySelector(`[data-chip="${t.toLowerCase()}"]`)?.className.includes('bg-neutral-700'), k)
    if (on) await chip(k)
  }
}
const mainHas = (text) => `[...document.querySelectorAll('.flex-1.overflow-auto')].some((e) => e.innerText.includes(${JSON.stringify(text)}))`
const sourceLine = () => page.evaluate(() => [...document.querySelectorAll('p')].find((p) => p.textContent.startsWith('Reading GitHub'))?.textContent || null)
const waitFor = async (fn, ms = 15000) => { for (let t = 0; t < ms; t += 100) { if (await page.evaluate(fn)) return true; await sleep(100) } return false }
const pct = (xs, p) => { const s = [...xs].sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))] }

try {
  // ── Tab first paint from saved state ──
  let mark = netLines().length
  report('Docs tab first paint (ms): click to project list with Unsorted', await clickTimed('button', 'Docs', `[...document.querySelectorAll('button')].some((e) => e.textContent.includes('Unsorted deliverables'))`, true))
  if (WARM) {
    // First launch: lets the background match pass save the map, and fills paper-dive's saved copy.
    await sleep(4000)
    await click('button', 'paper-dive', true)
    await sleep(6000)
    throw new Error('warm-only run finished')
  }

  // ── f-1: clarity-captions, no chip, a deliverable image open ──
  report('open project (local clone): tree painted (ms)', await clickTimed('button', 'clarity-captions', `[...document.querySelectorAll('.w-72 button')].some((e) => e.textContent.trim() === 'Project card') && [...document.querySelectorAll('.w-72 button')].some((e) => e.textContent.includes('seal-speak-ipad-2026-10-21'))`, true))
  await expand('seal-speak-ipad-2026-10-21')
  await waitFor(() => [...document.querySelectorAll('.w-72 button')].some((e) => e.textContent.includes('ipad-13-captions.png')))
  const imgReady = (n) => `(() => { const i = document.querySelector('.flex-1.overflow-auto img[alt="${n}"]'); return i && i.complete && i.naturalWidth > 0 })()`
  report('open image ipad-13-captions.png right after expanding its folder (folder grid still loading its covers) (ms)', await clickTimed('.w-72 button', 'ipad-13-captions.png', imgReady('ipad-13-captions.png')))
  await sleep(1500)
  const imgTimes = []
  for (const n of ['duo-folded-captions.png', 'duo-unfolded-captions.png', 'ipad-13-settings.png', 'ipad-13-captions.png', 'duo-folded-captions.png', 'ipad-13-settings.png']) imgTimes.push(await clickTimed('.w-72 button', n, imgReady(n)))
  report('open an image deliverable (~300 KB, 6): median / max (ms)', `${pct(imgTimes, 50)} / ${Math.max(...imgTimes)}`)
  await clickTimed('.w-72 button', 'ipad-13-captions.png', imgReady('ipad-13-captions.png'))
  await shot('f1-file-open')

  // ── f-2: Deliverables chip alone → the folder-card grid ──
  await chip('Deliverables')
  await click('button', 'clarity-captions', true)
  await waitFor(() => document.body.innerText.includes('newest first'))
  await sleep(1500)
  await shot('f2-deliverables-grid')

  // ── f-3: Docs + Decisions chips, project card ──
  await clearChips()
  await chip('Docs')
  await chip('Decisions')
  await click('button', 'clarity-captions', true)
  await waitFor(() => [...document.querySelectorAll('p')].some((p) => p.textContent.startsWith('Decisions') && p.textContent.includes('Show all')))
  await sleep(800)
  await shot('f3-docs-decisions')

  // ── Speed: text docs and text deliverables (all local), large image, PDF page ──
  await clearChips()
  mark = netLines().length
  const textTimes = []
  const docsToOpen = await page.evaluate(() => [...document.querySelectorAll('.w-72 button')].map((e) => e.textContent.trim()).filter((t) => /^(CONTEXT|README)\.md$/.test(t)))
  for (let round = 0; round < 10; round++) {
    for (const d of docsToOpen) textTimes.push(await clickTimed('.w-72 button', d, `(() => { const b = document.querySelector('.max-w-3xl'); return b && !document.body.innerText.includes('Loading…') && b.querySelector('h1,h2,p') })()`, true))
    await click('.w-72 button', 'Project card', true)
    await sleep(50)
  }
  // Decisions: open the group, then each of the first eight ADRs.
  await page.click('[data-group="decisions"]')
  await sleep(300)
  const adrs = await page.evaluate(() => [...document.querySelectorAll('.w-72 button')].map((e) => e.textContent.trim()).filter((t) => /^\d{4}-.*\.md$/.test(t)).slice(0, 8))
  for (const a of adrs) textTimes.push(await clickTimed('.w-72 button', a, `(() => { const b = document.querySelector('.max-w-3xl'); return b && !document.body.innerText.includes('Loading…') && b.querySelector('h1,h2,p') })()`, true))
  report(`open a text doc (${textTimes.length}): median / p95 / max (ms)`, `${pct(textTimes, 50)} / ${pct(textTimes, 95)} / ${Math.max(...textTimes)}`)

  // A markdown deliverable (rendered through FileView).
  await expand('seal-speak-app-store-2026-10-20')
  await waitFor(() => [...document.querySelectorAll('.w-72 button')].some((e) => e.textContent.includes('listing-1.0.md')))
  const mdTimes = []
  for (let i = 0; i < 10; i++) {
    mdTimes.push(await clickTimed('.w-72 button', 'listing-1.0.md', `(() => !!document.querySelector('.flex-1.overflow-auto h1, .flex-1.overflow-auto h2') && !document.body.innerText.includes('Loading…'))()`))
    await click('.w-72 button', 'Project card', true)
    await sleep(300)
  }
  await click('.w-72 button', '0-all-four.png')
  report('open a markdown deliverable (10): median / p95 / max (ms)', `${pct(mdTimes, 50)} / ${pct(mdTimes, 95)} / ${Math.max(...mdTimes)}`)
  report('  each (ms)', mdTimes)
  report('  text docs each (ms)', textTimes)
  await shot('folder-grid')

  // Large image (a full-page website screenshot).
  await expand('seal-speak-website-2026-10-20')
  await waitFor(() => [...document.querySelectorAll('.w-72 button')].some((e) => e.textContent.includes('light-option-paper-full.png')))
  const bigImg = []
  for (let i = 0; i < 5; i++) {
    bigImg.push(await clickTimed('.w-72 button', 'light-option-paper-full.png', `(() => { const i = document.querySelector('.flex-1.overflow-auto img[alt="light-option-paper-full.png"]'); return i && i.complete && i.naturalWidth > 0 })()`))
    await click('.w-72 button', 'dark-site-vs-app-harbor.png')
    await sleep(300)
  }
  const bigSize = fs.statSync(path.join(HOME, '.claude/outbox/seal-speak-website-2026-10-20/light-option-paper-full.png')).size
  report(`open a large image (${Math.round(bigSize / 1024)} KB, 5): median / max (ms)`, `${pct(bigImg, 50)} / ${Math.max(...bigImg)}`)

  // A 500-page PDF: time to its first page drawn.
  await click('button', 'marvin', true)
  await waitFor(() => [...document.querySelectorAll('.w-72 button')].some((e) => e.textContent.includes('marvin-570-speed-fixtures')))
  await expand('marvin-570-speed-fixtures-2026-10-21')
  await waitFor(() => [...document.querySelectorAll('.w-72 button')].some((e) => e.textContent.includes('handbook-500-pages.pdf')))
  const pdfTimes = []
  for (let i = 0; i < 5; i++) {
    pdfTimes.push(await clickTimed('.w-72 button', 'handbook-500-pages.pdf', `!!document.querySelector('.pdfViewer .page canvas')`))
    await click('.w-72 button', 'Project card', true)
    await sleep(300)
  }
  report('open a 500-page PDF, first page drawn (5): median / max (ms)', `${pct(pdfTimes, 50)} / ${Math.max(...pdfTimes)}`)
  report('  each (ms)', pdfTimes)
  const clickNet = netLines().slice(mark)
  report('network calls during all the clicks above (Docs-related)', clickNet.filter(isDocsNet).length)
  report('all gh/fetch lines in that window, by command', Object.entries(clickNet.reduce((m, l) => { const k = l.split(' ').slice(1, 4).join(' '); m[k] = (m[k] || 0) + 1; return m }, {})))

  // ── f-4: search with a chip ──
  await click('button', 'clarity-captions', true)
  await sleep(500)
  await chip('Deliverables')
  mark = netLines().length
  await page.fill('input[placeholder^="Search all docs and deliverables"]', 'app store')
  await waitFor(() => document.body.innerText.includes('the chip row filters results too'))
  await sleep(2000)
  await shot('f4-search-chip')
  // Open a search result (a deliverable): still no network.
  await click('button.rounded-lg', 'clarity-captions / outbox / seal-speak-app-store-2026-10-20/listing')
  await sleep(800)
  report('network calls while searching and opening a result (Docs-related)', netLines().slice(mark).filter(isDocsNet).length)
  await page.fill('input[placeholder^="Search all docs and deliverables"]', '')
  await clearChips()

  // ── f-5a / f-5b: GitHub-only project, saved copy first, then one conditional request ──
  // (Decisions start collapsed, as in the mock-up; the speed run above opened them.)
  if (await page.evaluate(() => document.querySelector('[data-group="decisions"]')?.textContent.trim().startsWith('▾'))) await page.click('[data-group="decisions"]')
  mark = netLines().length
  report('open GitHub-only project: tree painted from saved state (ms)', await clickTimed('button', 'paper-dive', `[...document.querySelectorAll('p')].some((p) => p.textContent.startsWith('Reading GitHub')) && [...document.querySelectorAll('.w-72 button')].some((e) => e.textContent.trim() === 'README.md')`, true))
  report('source line right after paint', await sourceLine())
  await shot('f5a-github-checking')
  await waitFor(() => /up to date|could not check/.test([...document.querySelectorAll('p')].find((p) => p.textContent.startsWith('Reading GitHub'))?.textContent || ''))
  report('source line settled', await sourceLine())
  await sleep(600)
  await shot('f5b-github-up-to-date')
  const ghOpen = netLines().slice(mark).filter(isDocsNet)
  report('GitHub-only open: Docs-related network calls', ghOpen.length)
  ghOpen.forEach((l) => console.log('   ', l))

  // ── Unsorted ──
  await click('button', 'Unsorted deliverables')
  await waitFor(() => document.body.innerText.includes('no project claims'))
  await sleep(1500)
  await shot('unsorted')
} catch (err) {
  if (!String(err).includes('warm-only')) {
    console.error('FAILED', err)
    await page.screenshot({ path: `${OUT}/failure.png` }).catch(() => {})
    console.error(await page.evaluate(() => [...document.querySelectorAll('.w-72 button')].slice(28, 80).map((e) => JSON.stringify(e.textContent)).join('\n')).catch(() => ''))
    process.exitCode = 1
  }
} finally {
  if (!WARM) fs.writeFileSync(path.join(OUT, 'ticket-570-evidence.json'), JSON.stringify(results, null, 2))
  await b?.close().catch(() => {})
  proc.kill('SIGTERM')
  await sleep(1500)
  try { proc.kill('SIGKILL') } catch {}
}
