// Evidence for #755 (opening an MR or a doc jumped to the bottom): drives the built app, records every scroll area's
// position at each step and screenshots it. Read-only: it only opens, scrolls and goes back.
// Usage: node scroll_memory_evidence.mjs <out-dir> [prefix]
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'
const APP = path.resolve(import.meta.dirname, '..'), [OUT, PREFIX = '755'] = process.argv.slice(2)
fs.mkdirSync(OUT, { recursive: true })
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
let b; for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page; for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
await page.setViewportSize({ width: 1280, height: 900 })
await sleep(9000)
const click = (sel, text) => page.evaluate(([s, t]) => {
  const el = [...document.querySelectorAll(s)].find((e) => !t || e.textContent.trim().startsWith(t))
  if (!el) throw new Error(`no ${s} ${t || ''}`)
  el.click()
}, [sel, text])
// Every element that scrolls vertically, with where it stands: top, the most it can scroll, and its height.
const scrollers = () => page.evaluate(() => [...document.querySelectorAll('*')]
  .filter((e) => e.scrollHeight > e.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(e).overflowY))
  .map((e) => ({ el: `${e.tagName.toLowerCase()}.${String(e.className).split(' ').slice(0, 3).join('.')}`, top: Math.round(e.scrollTop), max: e.scrollHeight - e.clientHeight })))
const log = []
const step = async (name) => { await sleep(900); const s = await scrollers(); log.push({ step: name, scrollers: s }); console.log(name, JSON.stringify(s)); await page.screenshot({ path: `${OUT}/${PREFIX}-${name}.png` }) }
try {
  await click('header button', 'MR Review')
  await page.waitForSelector('main [role="button"]', { timeout: 60000 }); await sleep(1500)
  // Scroll the list well down, then open the card nearest the middle of the window.
  await page.evaluate(() => { const m = document.querySelector('main'); m.scrollTop = Math.round((m.scrollHeight - m.clientHeight) * 0.7) })
  await step('01-list-scrolled')
  const opened = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('main [role="button"]')]
    const mid = window.innerHeight / 2
    const card = cards.sort((a, b) => Math.abs(a.getBoundingClientRect().top - mid) - Math.abs(b.getBoundingClientRect().top - mid))[0]
    const title = card.querySelector('p')?.textContent.slice(0, 60)
    card.click()
    return title
  })
  console.log('opened', opened)
  await step('02-mr-opened')
  await click('main button', '← Back to MR Review')
  await step('03-back-to-list')
  // The card you clicked should be on screen again, where it was.
  console.log('clicked card on screen:', await page.evaluate((t) => {
    const card = [...document.querySelectorAll('main [role="button"]')].find((c) => c.querySelector('p')?.textContent.startsWith(t))
    const r = card?.getBoundingClientRect(); return r ? { top: Math.round(r.top), visible: r.top >= 0 && r.bottom <= window.innerHeight } : null
  }, opened.slice(0, 20)))
  // A tab round trip remounts the list (it loads again): it should come back to the same place.
  await click('header button', 'Health'); await sleep(2000)
  await step('03b-health')
  await click('header button', 'MR Review'); await sleep(3000)
  await step('03c-mr-review-again')
  // Docs: open a project, scroll its overview to the bottom, open a doc from the tree; scroll it, open a second doc.
  await click('header button', 'Docs'); await sleep(2500)
  await page.evaluate(() => [...document.querySelectorAll('ul.overflow-auto button')].find((e) => e.textContent.trim().replace('●', '') === 'marvin').click())
  await sleep(3500)
  const pane = () => page.evaluate(() => { const c = [...document.querySelectorAll('div.flex-1.overflow-auto')].pop(); c.scrollTop = c.scrollHeight })
  await pane()
  await step('04-docs-overview-scrolled')
  const openTreeDoc = (n) => page.evaluate((n) => {
    const tree = document.querySelector('div.w-72 div.overflow-auto')
    const docs = [...tree.querySelectorAll('button')].filter((e) => /\.md$/.test(e.textContent.trim()) || /^\d{4}/.test(e.textContent.trim()))
    docs[n].click()
    return docs[n].textContent.trim()
  }, n)
  console.log('doc', await openTreeDoc(0))
  await step('05-doc-opened')
  await pane()
  await step('06-doc-scrolled')
  console.log('doc', await openTreeDoc(1))
  await step('07-second-doc-opened')
} finally {
  fs.writeFileSync(`${OUT}/${PREFIX}-scroll-log.json`, JSON.stringify(log, null, 2))
  await b.close(); proc.kill('SIGTERM')
}
