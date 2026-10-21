// Evidence capture for marvin#402 (Files tab shows every file readably; one shared image viewer with zoom). Drives the
// BUILT app (real CSP, real preload/IPC) against a sandbox HOME whose ~/.claude/outbox holds the fixtures, never the real
// one, attaches over CDP, screenshots each view and checks the viewer's closing paths with real mouse events.
// Usage: npm run build && HOME=<sandbox with .claude/outbox> node scripts/files_viewer_evidence.mjs <out-dir>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT] = process.argv.slice(2)
const HOME = process.env.HOME
if (!OUT || HOME === '/Users/gileskayo' || !fs.existsSync(path.join(HOME, '.claude', 'outbox'))) {
  console.error('usage: HOME=<sandbox with .claude/outbox> node files_viewer_evidence.mjs <out-dir>')
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
await page.setViewportSize({ width: 1280, height: 820 })
await sleep(9000)

const results = []
const consoleLines = []
page.on('console', (m) => consoleLines.push(m.text()))
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ` (${detail})` : ''}`) }
const shot = async (name) => { await sleep(900); await page.screenshot({ path: `${OUT}/ticket-402-${name}.png` }); console.log('shot', name) }
const clickText = (sel, text) => page.evaluate(([s, t]) => {
  const el = [...document.querySelectorAll(s)].find((e) => e.textContent.trim().startsWith(t) || (e.title || '').startsWith(t))
  if (!el) throw new Error(`no ${s} ${t}`)
  el.click()
}, [sel, text])
const openFile = async (rel) => {
  const parts = rel.split('/')
  for (let i = 1; i < parts.length; i++) {
    const dir = parts.slice(0, i).join('/')
    const expanded = await page.evaluate((d) => !![...document.querySelectorAll('button')].find((e) => e.title === d && e.textContent.includes('▼')), dir)
    if (!expanded) await page.evaluate((d) => [...document.querySelectorAll('button')].find((e) => e.title === d).click(), dir)
    await sleep(150)
  }
  await page.evaluate((r) => [...document.querySelectorAll('button')].find((e) => (e.title || '').startsWith(`${r} · `)).click(), rel)
  await sleep(1200)
}
const viewerOpen = () => page.evaluate(() => !!document.querySelector('[data-image-viewer]'))
const rect = (sel) => page.evaluate((s) => { const r = document.querySelector(s)?.getBoundingClientRect(); return r && { x: r.x, y: r.y, w: r.width, h: r.height } }, sel)
// A dot showing where the next real mouse click lands (evidence annotation only; it takes no clicks).
const markClick = (x, y) => page.evaluate(([px, py]) => {
  const d = document.createElement('div')
  d.id = 'evidence-click-marker'
  Object.assign(d.style, { position: 'fixed', left: `${px - 14}px`, top: `${py - 14}px`, width: '28px', height: '28px', borderRadius: '50%', border: '3px solid #f43f5e', background: 'rgba(244,63,94,.25)', zIndex: 9999, pointerEvents: 'none' })
  document.body.appendChild(d)
}, [x, y])
const unmark = () => page.evaluate(() => document.getElementById('evidence-click-marker')?.remove())

try {
  await clickText('button', 'Files')
  await sleep(1500)

  // 1. An outbox PNG (one of the 2026-10-09 mock-ups), with each file's kind in the list.
  await openFile('portfolio-mockups-2026-10-09/shots/mock-home-1.png')
  const imgOk = await page.evaluate(() => { const i = document.querySelector('main img, .flex-1 img[alt="mock-home-1.png"]'); return !!i && i.complete && i.naturalWidth > 0 })
  check('outbox PNG displays (real CSP)', imgOk)
  const labels = await page.evaluate(() => [...document.querySelectorAll('button span.rounded')].map((s) => s.textContent))
  check('file list shows kinds in plain words', labels.includes('Image'), [...new Set(labels)].join(', '))
  await shot('files-png')

  // 2. Markdown with embedded relative images (resolved against its folder), and a ../ escape refused.
  await openFile('portfolio-mockups-2026-10-09/mockup-notes.md')
  await sleep(1500)
  const md = await page.evaluate(() => ({
    loaded: [...document.querySelectorAll('img')].filter((i) => i.src.startsWith('data:image/png') && i.naturalWidth > 0).length,
    refused: document.body.innerText.includes("couldn't load")
  }))
  check('markdown embedded images display', md.loaded >= 2, `${md.loaded} loaded`)
  check('markdown ../ escape refused', md.refused)
  await shot('files-markdown-images')

  // 3. CSV as a table.
  await openFile('data/ticket-throughput.csv')
  const cell = await page.evaluate(() => [...document.querySelectorAll('td')].some((t) => t.textContent === 'steady, no incidents'))
  check('CSV table keeps quoted commas in one cell', cell)
  await shot('files-csv')

  // 4. PDFs: pdf.js's interactive viewer (text, links, forms, find) in the dashboard's style, with our toolbar.
  const pdfStats = () => page.evaluate(() => ({
    count: document.querySelector('[data-pdf-count]')?.textContent,
    current: document.querySelector('[data-pdf-page-input]')?.value,
    pages: document.querySelectorAll('.pdfViewer .page').length,
    rendered: [...document.querySelectorAll('.pdfViewer .page')].filter((e) => e.querySelector('canvas')).map((e) => Number(e.dataset.pageNumber)),
    iframe: !!document.querySelector('iframe')
  }))
  const waitFor = async (fn, ms = 8000) => { for (let t = 0; t < ms; t += 150) { if (await page.evaluate(fn)) return true; await sleep(150) } return false }
  await openFile('data/weekly-report.pdf')
  await waitFor(() => !!document.querySelector('.pdfViewer .page canvas'))
  await sleep(800)
  check('pdf.js runs in its real worker from the app bundle (no fake-worker fallback)', !consoleLines.some((l) => /fake worker/i.test(l)), consoleLines.filter((l) => /pdf|worker/i.test(l)).slice(0, 3).join(' | ') || 'no pdf.js warnings')
  const p12 = await pdfStats()
  check('a 12-page PDF shows "12 pages" and draws its pages itself (no Chromium viewer)', p12.count === '12 pages' && p12.pages === 12 && p12.rendered.includes(1) && !p12.iframe, JSON.stringify(p12))
  await shot('files-pdf')

  // A 500-page handbook: outline, page jump, scroll-following indicator, find, links.
  await openFile('data/handbook-500-pages.pdf')
  await waitFor(() => !!document.querySelector('.pdfViewer .page canvas'))
  await sleep(1000)
  const outlineTitles = await page.evaluate(() => [...document.querySelectorAll('[data-pdf-outline] button')].map((b) => b.textContent))
  check('the outline sidebar lists the bookmarks', outlineTitles.includes('Part 2: Health') && outlineTitles.includes('1.1 Dispatch'), outlineTitles.join(' / '))
  const first = await pdfStats()
  check('opening a 500-page PDF renders only its first pages', first.pages === 500 && first.rendered.length <= 3, `rendered ${first.rendered.join(',')}`)
  await shot('files-pdf-outline')
  await page.fill('[data-pdf-page-input]', '400')
  await page.press('[data-pdf-page-input]', 'Enter')
  await sleep(1800)
  const j = await pdfStats()
  const near = j.rendered.filter((n) => n >= 395 && n <= 405)
  const stray = j.rendered.filter((n) => !(n >= 395 && n <= 405) && !first.rendered.includes(n))
  check('jumping to page 400 renders only page 400 and its neighbours', j.current === '400' && near.includes(400) && stray.length === 0 && j.rendered.length <= 10, `now on ${j.current}; rendered ${j.rendered.join(',')}`)
  await shot('files-pdf-jump-400')
  await page.evaluate(() => [...document.querySelectorAll('[data-pdf-outline] button')].find((b) => b.textContent === 'Part 2: Health').click())
  await sleep(1200)
  check('clicking an outline entry jumps there', (await pdfStats()).current === '250')
  await page.evaluate(() => { const sc = document.querySelector('[data-pdf-scroll]'); const p = document.querySelector('.pdfViewer .page[data-page-number="120"]'); sc.scrollTop = p.offsetTop + 50 })
  await sleep(1000)
  check('the page indicator follows scrolling', (await pdfStats()).current === '120', (await pdfStats()).current)
  await page.click('button[aria-label="Previous page"]')
  await sleep(600)
  check('previous page button', (await pdfStats()).current === '119', (await pdfStats()).current)

  // Find (⌘F with the PDF focused): many matches, then none.
  await page.focus('[data-pdf-scroll]')
  await page.keyboard.press('Meta+f')
  await sleep(300)
  check('⌘F opens find in the PDF', await page.evaluate(() => document.activeElement?.getAttribute('aria-label') === 'Find in PDF'))
  await page.keyboard.type('throughput')
  await waitFor(() => /of 500 matches/.test(document.querySelector('[data-pdf-find-status]')?.textContent || ''), 30000)
  const fs1 = await page.evaluate(() => ({ status: document.querySelector('[data-pdf-find-status]').textContent, highlights: document.querySelectorAll('.textLayer .highlight').length }))
  check('find counts every match and highlights them', /of 500 matches/.test(fs1.status) && fs1.highlights > 0, JSON.stringify(fs1))
  await page.keyboard.press('Enter')
  await sleep(500)
  const fs2 = await page.evaluate(() => document.querySelector('[data-pdf-find-status]').textContent)
  // pdf.js starts at the first match from the current page (as Chrome's viewer does), so check the step, not the number.
  const k = parseInt(fs1.status, 10)
  check('Enter goes to the next match', parseInt(fs2, 10) === k + 1, `${fs1.status} → ${fs2}`)
  await shot('files-pdf-find')
  await page.fill('[aria-label="Find in PDF"]', 'zzqqxx')
  await waitFor(() => document.querySelector('[data-pdf-find-status]')?.textContent === 'No matches', 30000)
  check('find with no matches says so', (await page.evaluate(() => document.querySelector('[data-pdf-find-status]').textContent)) === 'No matches')
  await page.keyboard.press('Escape')
  await sleep(300)

  // Links on page 1: internal jumps; only the https link has a target; javascript:/file: never become links.
  await page.fill('[data-pdf-page-input]', '1')
  await page.press('[data-pdf-page-input]', 'Enter')
  await waitFor(() => document.querySelectorAll('.pdfViewer .page[data-page-number="1"] .annotationLayer a').length > 0)
  await sleep(600)
  const links = await page.evaluate(() => [...document.querySelectorAll('.pdfViewer .page[data-page-number="1"] .annotationLayer a')].map((a) => a.getAttribute('href') || ''))
  check('internal and https links are live; javascript: and file: links are refused', links.length === 2 && links.some((h) => h.startsWith('#')) && links.includes('https://example.com/') && !links.some((h) => /^(javascript|file):/i.test(h)), links.join(' '))
  const ext = await rect('.pdfViewer .page[data-page-number="1"] .annotationLayer a[href^="https"]')
  await page.mouse.move(ext.x + 5, ext.y + 5)
  await page.mouse.move(ext.x + ext.w / 2, ext.y + ext.h / 2, { steps: 4 })
  await sleep(400)
  const hovered = await page.evaluate(() => {
    const a = document.querySelector('.annotationLayer a[href^="https"]:hover')
    if (!a) return null
    const cs = getComputedStyle(a)
    const r = a.getBoundingClientRect()
    return { bg: cs.backgroundColor, opacity: cs.opacity, w: Math.round(r.width), h: Math.round(r.height) }
  })
  check('the hovered link highlights', !!hovered && hovered.bg !== 'rgba(0, 0, 0, 0)' && hovered.w > 0, JSON.stringify(hovered))
  await page.hover('.annotationLayer a[href^="https"]')
  await page.screenshot({ path: `${OUT}/ticket-402-files-pdf-link-hover.png` })
  await page.click('.pdfViewer .page[data-page-number="1"] .annotationLayer a[href^="#"]')
  await sleep(900)
  check('an internal link jumps to its page', (await pdfStats()).current === '3', (await pdfStats()).current)

  // In-place zoom keeps text, links and forms usable.
  await page.click('[data-pdf-toolbar] button[aria-label="Zoom in"]')
  await page.click('[data-pdf-toolbar] button[aria-label="Zoom in"]')
  await sleep(900)
  const zoomed = await page.evaluate(() => ({ level: document.querySelector('[data-pdf-toolbar] [aria-label="Zoom level"]').textContent, text: document.querySelectorAll('.pdfViewer .page .textLayer span').length }))
  check('in-place zoom keeps the text layer', parseInt(zoomed.level, 10) > 100 && zoomed.text > 0, JSON.stringify(zoomed))
  await page.click('[data-pdf-toolbar] button:has-text("Fit width")')
  await sleep(500)

  // A form: type, tick, choose. The file on disk must not change.
  const formFile = path.join(HOME, '.claude', 'outbox', 'data', 'signup-form.pdf')
  const formBefore = fs.readFileSync(formFile)
  await openFile('data/signup-form.pdf')
  await waitFor(() => !!document.querySelector('.annotationLayer input[type="text"], .annotationLayer textarea'))
  await sleep(600)
  await page.click('.annotationLayer .textWidgetAnnotation input, .annotationLayer .textWidgetAnnotation textarea')
  await page.keyboard.type('Gil Eskayo')
  await page.click('.annotationLayer .buttonWidgetAnnotation.checkBox input')
  await page.selectOption('.annotationLayer .choiceWidgetAnnotation select', 'Blue')
  await sleep(400)
  const form = await page.evaluate(() => ({
    text: document.querySelector('.annotationLayer .textWidgetAnnotation input, .annotationLayer .textWidgetAnnotation textarea').value,
    checked: document.querySelector('.annotationLayer .buttonWidgetAnnotation.checkBox input').checked,
    choice: document.querySelector('.annotationLayer .choiceWidgetAnnotation select').value,
    note: document.querySelector('[data-pdf-form-note]')?.textContent
  }))
  check('form fields take typing, a tick and a choice, and the UI says edits are not saved', form.text === 'Gil Eskayo' && form.checked && form.choice === 'Blue' && /aren't saved/.test(form.note || ''), JSON.stringify(form))
  await shot('files-pdf-form')
  check('the PDF file on disk is unchanged', fs.readFileSync(formFile).equals(formBefore))

  await openFile('data/locked.pdf')
  await sleep(1500)
  const locked = await page.evaluate(() => document.querySelector('[data-file-card]')?.innerText || '')
  check('a password-protected PDF gets the card with the reason', /password-protected/i.test(locked), locked.replace(/\n/g, ' | '))
  await shot('files-pdf-locked')
  await openFile('data/corrupt.pdf')
  await sleep(1500)
  const corrupt = await page.evaluate(() => document.querySelector('[data-file-card]')?.innerText || '')
  check('a corrupt PDF gets the card', /damaged|couldn't be read|no pages/i.test(corrupt), corrupt.replace(/\n/g, ' | '))

  // A page opened full size in the shared viewer, zoomed like any image.
  await openFile('data/weekly-report.pdf')
  await waitFor(() => !!document.querySelector('.pdfViewer .page canvas'))
  await page.click('[data-pdf-toolbar] button:has-text("Full size")')
  for (let i = 0; i < 40 && !(await viewerOpen()); i++) await sleep(150)
  await sleep(800)
  const pv = await page.evaluate(() => { const i = document.querySelector('[data-viewer-scroll] img'); return i && { w: i.naturalWidth, h: i.naturalHeight } })
  check('⤢ Full size opens the page sharp in the shared viewer', !!pv && pv.h >= 3000, JSON.stringify(pv))
  const psc = await rect('[data-viewer-scroll]')
  await page.mouse.move(psc.x + psc.w / 2, psc.y + 160)
  await page.keyboard.down('Meta')
  for (let i = 0; i < 3; i++) { await page.mouse.wheel(0, -100); await sleep(80) }
  await page.keyboard.up('Meta')
  await sleep(500)
  const pz = await page.evaluate(() => document.querySelector('[data-image-viewer] [aria-label="Zoom level"]').textContent)
  check('the PDF page zooms like an image', parseInt(pz, 10) > 30, pz)
  await shot('viewer-pdf-page-zoomed')
  await page.keyboard.press('Escape')
  await sleep(300)

  // 5. HTML rendered sandboxed.
  await openFile('seal-speak-ipad-2026-10-21/seal-speak-ipad-duo.html')
  await sleep(2000)
  const sb = await page.evaluate(() => document.querySelector('iframe[sandbox]')?.getAttribute('sandbox'))
  check('HTML iframe has an empty sandbox (no scripts)', sb === '', JSON.stringify(sb))
  await shot('files-html')

  // 5b. A hostile page: its script must not run and nothing may load from the network. Chromium still reports a
  // request the CSP refuses (as failed, reason "csp"), so a load counts only if it got a response or failed otherwise.
  const loaded = []
  const blocked = []
  const remoteUrl = (u) => /^https?:/.test(u) && !u.startsWith('http://localhost')
  const onResp = (r) => { if (remoteUrl(r.url())) loaded.push(`${r.status()} ${r.url()}`) }
  const onFail = (r) => { if (remoteUrl(r.url())) (r.failure()?.errorText === 'csp' ? blocked : loaded).push(r.url()) }
  page.on('response', onResp)
  page.on('requestfailed', onFail)
  await openFile('data/hostile.html')
  await sleep(2500)
  const frame = page.frames().find((f) => f !== page.mainFrame() && f.url() === 'about:srcdoc')
  const title = frame ? await frame.evaluate(() => document.title).catch((e) => `unreadable: ${e.message}`) : 'no frame'
  check('a script in an HTML file does not run', title === 'original', `title=${title}`)
  check('an HTML file loads nothing from the network', loaded.length === 0, `${loaded.length} loaded; blocked by CSP: ${blocked.join(' ') || 'none'}`)
  check('the page stays put (meta refresh removed)', page.frames().some((f) => f.url() === 'about:srcdoc'))
  page.off('response', onResp)
  page.off('requestfailed', onFail)
  await shot('files-html-hostile')

  // 6. The card for a file with no readable form.
  await openFile('data/fake.png')
  check('a text file named .png gets the card', !!(await page.evaluate(() => document.querySelector('[data-file-card]'))))
  await shot('files-card')

  // 7. The shared image viewer: a tall full-page screenshot opens fit-to-width.
  await openFile('portfolio-mockups-2026-10-09/current/marvin.png')
  await page.click('img[alt="marvin.png"]')
  await sleep(800)
  check('clicking an inline image opens the viewer', await viewerOpen())
  const tall = await page.evaluate(() => {
    const sc = document.querySelector('[data-viewer-scroll]')
    const img = sc.querySelector('img')
    return { imgW: img.getBoundingClientRect().width, scW: sc.clientWidth, scrolls: sc.scrollHeight > sc.clientHeight }
  })
  check('tall screenshot opens fit-to-width and scrolls', Math.abs(tall.imgW - Math.min(1280, tall.scW)) < 2 && tall.scrolls, JSON.stringify(tall))
  await shot('viewer-tall-fit-width')

  // Zoom in with ⌘-scroll at a point, then the + button.
  const sc = await rect('[data-viewer-scroll]')
  await page.mouse.move(sc.x + sc.w * 0.3, sc.y + 200)
  await page.keyboard.down('Meta')
  for (let i = 0; i < 4; i++) { await page.mouse.wheel(0, -100); await sleep(80) }
  await page.keyboard.up('Meta')
  await page.click('button[aria-label="Zoom in"]')
  await sleep(500)
  const zoom = await page.evaluate(() => document.querySelector('[aria-label="Zoom level"]').textContent)
  check('⌘-scroll and + zoom in', parseInt(zoom, 10) > 100, zoom)
  await shot('viewer-zoomed')
  // ✕ closes (a real mouse click at the button's position).
  const x = await rect('button[aria-label="Close"]')
  const header = await rect('header.titlebar')
  const overlaps = header && x.y < header.y + header.h
  const region = await page.evaluate(() => getComputedStyle(document.querySelector('[data-image-viewer]')).webkitAppRegion)
  check('✕ sits over the title-bar drag strip, and the viewer opts out of it', overlaps && region === 'no-drag', `header bottom ${header && Math.round(header.y + header.h)}px, ✕ top ${Math.round(x.y)}px, app-region ${region}`)
  await page.mouse.click(x.x + x.w / 2, x.y + x.h / 2)
  await sleep(400)
  check('✕ closes the viewer', !(await viewerOpen()))

  // An iPad screenshot (fits whole, with room beside it): double-click zoom, then close by clicking beside the picture.
  await openFile('seal-speak-ipad-2026-10-21/ipad-13-captions.png')
  await page.click('img[alt="ipad-13-captions.png"]')
  await sleep(800)
  await page.click('button[aria-label="Fit"]')
  await sleep(300)
  const img = await rect('[data-viewer-scroll] img')
  const sc2 = await rect('[data-viewer-scroll]')
  // Double-click toggles Fit ↔ 100%.
  await page.mouse.dblclick(img.x + img.w / 2, img.y + img.h / 2)
  await sleep(400)
  const afterDbl = await page.evaluate(() => document.querySelector('[aria-label="Zoom level"]').textContent)
  check('double-click toggles Fit → 100%', afterDbl === '100%', afterDbl)
  await shot('viewer-100-after-double-click')
  // Drag to pan at 100%, then confirm neither the drag nor a click on the picture closed it.
  const before = await page.evaluate(() => document.querySelector('[data-viewer-scroll]').scrollTop)
  await page.mouse.move(sc2.x + sc2.w / 2, sc2.y + sc2.h / 2)
  await page.mouse.down()
  await page.mouse.move(sc2.x + sc2.w / 2, sc2.y + sc2.h / 2 - 200, { steps: 8 })
  await page.mouse.up()
  await sleep(300)
  const after = await page.evaluate(() => document.querySelector('[data-viewer-scroll]').scrollTop)
  check('drag pans when zoomed', after > before, `scrollTop ${before} → ${after}`)
  await page.mouse.click(sc2.x + sc2.w / 2, sc2.y + sc2.h / 2)
  await sleep(300)
  check('a drag or a click on the picture does not close it', await viewerOpen())
  await page.click('button[aria-label="Fit"]')
  await sleep(300)
  const img2 = await rect('[data-viewer-scroll] img')
  const pt = { x: (sc2.x + img2.x) / 2, y: img2.y + img2.h / 2 }   // midway between the window edge and the picture
  check('the picture has room beside it to click', img2.x - sc2.x > 40, `gap ${Math.round(img2.x - sc2.x)}px`)
  await markClick(pt.x, pt.y)
  await shot('viewer-before-click-outside')
  await unmark()
  await page.mouse.click(pt.x, pt.y)
  await sleep(400)
  check('a click beside the picture closes the viewer', !(await viewerOpen()), `clicked ${Math.round(pt.x)},${Math.round(pt.y)}`)
  await shot('viewer-closed-after-click-outside')

  // Esc closes too.
  await page.click('img[alt="ipad-13-captions.png"]')
  await sleep(500)
  check('viewer reopened for the Esc check', await viewerOpen())
  await page.keyboard.press('Escape')
  await sleep(300)
  check('Esc closes the viewer', !(await viewerOpen()))
} catch (err) {
  console.error('evidence run failed:', err)
  check('evidence run completed', false, String(err?.message || err))
} finally {
  await b?.close().catch(() => {})
  proc.kill('SIGTERM')
  setTimeout(() => proc.kill('SIGKILL'), 1500).unref()
}
fs.writeFileSync(path.join(OUT, 'ticket-402-checks.json'), JSON.stringify(results, null, 2))
process.exit(results.every((r) => r.ok) ? 0 : 1)
