// Mock-up evidence for the Vitals Accounts card (marvin#640/#974): renders src/components/AccountsCard.jsx with real
// rows (from `accounts.py check --json` on each machine; no secrets in them) and the dashboard's built CSS, and
// screenshots it with this checkout's Electron. The card is not mounted in the app until Gil approves it.
// Usage: npx electron-vite build && node scripts/accounts_mock_evidence.mjs <rows.json> <out.png> [thisMachine] [width]
import { build } from 'esbuild'
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'

const APP = path.resolve(import.meta.dirname, '..')
const [ROWS, OUT, THIS = 'mac-mini-1', WIDTH = '880'] = process.argv.slice(2)
if (!ROWS || !OUT) { console.error('usage: node accounts_mock_evidence.mjs <rows.json> <out.png> [thisMachine] [width]'); process.exit(1) }
const css = fs.readdirSync(path.join(APP, 'out/renderer/assets')).find((f) => /^index-.*\.css$/.test(f))
if (!css) { console.error('no built CSS: run `npx electron-vite build` first'); process.exit(1) }
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'accounts-mock-'))
const entry = `import { renderToStaticMarkup } from 'react-dom/server'; import { AccountsCard } from ${JSON.stringify(path.join(APP, 'src/components/AccountsCard.jsx'))};
module.exports = (rows, thisMachine, now) => renderToStaticMarkup(AccountsCard({ rows, thisMachine, now, checkedAt: '2 min ago' }))`
const out = await build({ stdin: { contents: entry, resolveDir: APP, loader: 'jsx' }, bundle: true, platform: 'node', format: 'cjs', write: false, jsx: 'automatic', logLevel: 'silent' })
const mod = path.join(tmp, 'render.cjs')
fs.writeFileSync(mod, out.outputFiles[0].text)
const render = createRequire(import.meta.url)(mod)
const markup = render(JSON.parse(fs.readFileSync(ROWS, 'utf8')), THIS, Date.now())
const html = path.join(tmp, 'card.html')
fs.writeFileSync(html, `<!doctype html><html class="dark"><head><meta charset="utf-8"><link rel="stylesheet" href="${path.join(APP, 'out/renderer/assets', css)}"></head><body class="bg-neutral-950" style="margin:0;padding:24px;width:${WIDTH - 48}px">${markup}</body></html>`)
const main = path.join(tmp, 'main.cjs')
fs.writeFileSync(main, `const { app, BrowserWindow } = require('electron'); const fs = require('fs')
app.whenReady().then(async () => {
  const w = new BrowserWindow({ show: false, width: ${Number(WIDTH)}, height: 800, webPreferences: { offscreen: true } })
  await w.loadFile(${JSON.stringify(html)})
  const h = await w.webContents.executeJavaScript('document.documentElement.scrollHeight')
  w.setSize(${Number(WIDTH)}, Math.min(h + 4, 4000)); await new Promise((r) => setTimeout(r, 400))
  fs.writeFileSync(${JSON.stringify(path.resolve(OUT))}, (await w.webContents.capturePage()).toPNG()); app.quit()
})`)
const bin = process.platform === 'darwin' ? path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron') : path.join(APP, 'node_modules/electron/dist/electron')
const r = spawnSync(bin, [main], { stdio: 'inherit', timeout: 60_000 })
fs.rmSync(tmp, { recursive: true, force: true })
if (r.status !== 0 || !fs.existsSync(OUT)) { console.error('capture failed'); process.exit(1) }
console.log(OUT)
