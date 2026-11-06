// Screenshots for marvin show slice 2 (#715): the history strip in the show window, in #1029's celestial-navigation
// look. Loads the BUILT renderer page (out/renderer, `npm run build` first) with #show=<project>, exactly as a show
// window does, in headless Chrome. window.api.show is stood in for by a page-side stub that keeps the same contract
// as electron/main/show_window.js (current/onItem/read/select), with files read through the real fileFromBuffer, so
// nothing is shown to Gil, no window opens and no real show store is touched.
//   node scripts/show_history_evidence.mjs <out-dir>
import { chromium } from 'playwright-core'
import { createServer } from 'node:http'
import path from 'node:path'
import fs from 'node:fs'
import { fileFromBuffer } from '../electron/main/outbox.js'

const APP = path.resolve(import.meta.dirname, '..')
const ROOT = path.join(APP, 'out', 'renderer')
const [OUT] = process.argv.slice(2)
if (!OUT) {
  console.error('usage: node scripts/show_history_evidence.mjs <out-dir>')
  process.exit(1)
}
if (!fs.existsSync(path.join(ROOT, 'index.html'))) {
  console.error('no built renderer: run `npm run build` first')
  process.exit(1)
}
fs.mkdirSync(OUT, { recursive: true })

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png' }
const server = createServer((req, res) => {
  const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(/^\/+/, '') || 'index.html'
  const file = path.resolve(ROOT, rel)
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404)
    return res.end()
  }
  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream' })
  res.end(fs.readFileSync(file))
})
await new Promise((r) => server.listen(0, '127.0.0.1', r))
const port = server.address().port

// Three earlier items for the MARVIN project, as show_window.js's publicItem() sends them.
const at = Date.parse('2026-11-04T18:42:00Z')
const md = (name, text) => fileFromBuffer({ name, path: `~/.claude/outbox/marvin-2026-11-04-show/${name}`, size: text.length }, Buffer.from(text))
const items = {
  h3: { kind: 'markdown', label: 'site-deploy-plan.md', at, file: md('site-deploy-plan.md', '# Site deploy\n\nEvery merge to main builds the site and publishes it to GitHub Pages.\n\n- The CNAME comes from site.config.json\n- A failed deploy raises a Health alert, once per commit\n') },
  h2: { kind: 'markdown', label: 'verify-timeout.md', at: at - 9 * 60e3, file: md('verify-timeout.md', '# Verify timeout\n\nThe 20-minute clock stops while a build waits in line for the test slot.\n') },
  h1: { kind: 'markdown', label: 'review-list.md', at: at - 31 * 60e3, file: md('review-list.md', '# The Review list\n\n7 merged today.\n') }
}
const order = ['h3', 'h2', 'h1']

const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 920, height: 600 }, deviceScaleFactor: 2 })
await page.addInitScript(({ items, order }) => {
  const project = { id: 'marvin', name: 'MARVIN' }
  let current = order[0]
  const listeners = []
  const history = () => order.map((id) => ({ id, label: items[id].label, kind: items[id].kind, at: items[id].at }))
  const item = () => ({ kind: items[current].kind, label: items[current].label, path: items[current].file.path, project, historyId: current, history: history() })
  window.api = {
    show: {
      current: async () => item(),
      onItem: (cb) => { listeners.push(cb); return () => {} },
      onWeb: () => () => {},
      read: async () => items[current].file,
      image: async () => null,
      openLink: () => {},
      openInDocs: () => {},
      setWebBounds: () => {},
      select: async (id) => {
        if (!items[id]) return { ok: false, reason: 'Not in this window\'s history' }
        current = id
        setTimeout(() => listeners.forEach((cb) => cb(item())), 0)
        return { ok: true }
      }
    }
  }
}, { items, order })

await page.goto(`http://127.0.0.1:${port}/index.html#show=marvin`)
await page.waitForSelector('[data-history-strip]')
await page.waitForTimeout(600)
await page.screenshot({ path: path.join(OUT, '7-history-strip.png') })
await page.click('[data-history-strip] button[title="verify-timeout.md"]')
await page.waitForFunction(() => document.querySelector('[data-history-strip] [aria-current="true"]')?.title === 'verify-timeout.md')
await page.waitForTimeout(400)
await page.screenshot({ path: path.join(OUT, '8-history-strip-click-shows-it-again.png') })
await browser.close()
server.close()
console.log(`wrote 2 shots to ${OUT}`)
