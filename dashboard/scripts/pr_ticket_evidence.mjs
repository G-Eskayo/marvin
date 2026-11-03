// Evidence for marvin#1004 (a PR names its ticket as "Closes" or "Part of", across repos): renders the real board Card
// and MR Review TicketLine components, fed by the real board and parity code over a saved snapshot of every board's
// GitHub data, with the app's built stylesheet, and screenshots the page in Electron. Read-only: no GitHub calls.
// Usage (after `npm run build`): npx vite-node scripts/pr_ticket_evidence.mjs <boards-data.json> <out.png>
//   boards-data.json: { "<owner/repo>": fetchBoardData(repo) for every board } (fetched once, beforehand)
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync, readdirSync, writeFileSync, mkdtempSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { buildBoard } from '../electron/main/board.js'
import { createRelationsService } from '../electron/main/relations_service.js'
globalThis.React = React // vite-node compiles JSX with the classic runtime
const { Card } = await import('../src/components/ProjectBoard.jsx')
const { TicketLine } = await import('../src/components/MrReview.jsx')

const APP = path.resolve(import.meta.dirname, '..')
const [dataFile, outPng] = process.argv.slice(2)
if (!dataFile || !outPng) {
  console.error('usage: npx vite-node scripts/pr_ticket_evidence.mjs <boards-data.json> <out.png>')
  process.exit(1)
}
const data = JSON.parse(readFileSync(dataFile, 'utf-8'))
const allPrs = Object.entries(data).flatMap(([repo, d]) => d.prs.map((p) => ({ ...p, repo })))
const cardOf = (repo, number) => {
  const b = buildBoard({ repo, issues: data[repo].issues, prs: allPrs })
  return b.columns.flatMap((c) => c.cards.map((k) => ({ ...k, column: c.label }))).find((k) => k.number === number)
}
const parity = await createRelationsService({
  getRepos: () => Object.keys(data), getBoardData: async (r) => data[r], getDocs: async () => [], getProjects: () => []
}).parity()

const [owner] = Object.keys(data)[0].split('/')
const cards = [[`${owner}/marvin`, 623], [`${owner}/marvin`, 949], [`${owner}/clarity-captions`, 235]].map(([r, n]) => ({ repo: r, card: cardOf(r, n) }))
const flagged = new Set(['clarity-captions#258', 'clarity-captions#255', 'clarity-captions#231', 'marvin-instance#11', 'marvin-instance#9', 'marvin-instance#5', 'marvin-instance#6'])
const rows = parity.prs.filter((r) => flagged.has(`${r.repo.split('/')[1]}#${r.number}`))
const h = React.createElement
const page = h('div', { className: 'p-6 space-y-6', style: { width: 1100 } },
  h('h2', { className: 'text-sm font-semibold text-neutral-300' }, 'Board cards (Activity): a PR in any repo that closes or is part of the ticket puts it In review'),
  h('div', { className: 'grid grid-cols-3 gap-3' }, ...cards.map(({ repo, card }) =>
    h('div', { key: `${repo}#${card.number}` },
      h('p', { className: 'mb-1 text-[10px] uppercase tracking-wide text-neutral-500' }, `${repo.split('/')[1]} board · ${card.column}`),
      h(Card, { card, repo, onSelect: () => {}, onOpenMr: () => {}, activeTags: new Set(), onTag: () => {} })))),
  h('h2', { className: 'text-sm font-semibold text-neutral-300' }, `MR Review ticket lines for the seven PRs the parity check flagged (now: ${parity.problems.length} problems over ${parity.prs.length} open PRs)`),
  h('div', { className: 'space-y-2' }, ...rows.map((row) =>
    h('div', { key: row.key, className: 'rounded border border-neutral-800 bg-neutral-900 px-3 py-2' },
      h('p', { className: 'text-xs font-mono text-neutral-400' }, `${row.repo.split('/')[1]} PR #${row.number}`),
      h(TicketLine, { row, onOpenTicket: () => {} })))))

const assets = path.join(APP, 'out', 'renderer', 'assets')
const css = readdirSync(assets).find((f) => /^index-.*\.css$/.test(f))
const dir = mkdtempSync(path.join(tmpdir(), 'pr-ticket-evidence-'))
const html = path.join(dir, 'page.html')
writeFileSync(html, `<!doctype html><html class="dark"><head><meta charset="utf-8"><link rel="stylesheet" href="file://${path.join(assets, css)}"></head>` +
  `<body style="background:#0a0a0a;margin:0">${renderToStaticMarkup(page)}</body></html>`)
const main = path.join(dir, 'main.cjs')
writeFileSync(main, `const { app, BrowserWindow } = require('electron'); const fs = require('fs')
app.whenReady().then(async () => {
  const w = new BrowserWindow({ show: false, width: 1150, height: 900, webPreferences: { offscreen: true } })
  await w.loadFile(${JSON.stringify(html)})
  const h = await w.webContents.executeJavaScript('document.body.scrollHeight')
  w.setContentSize(1150, h)
  await new Promise((r) => setTimeout(r, 600))
  fs.writeFileSync(${JSON.stringify(path.resolve(outPng))}, (await w.webContents.capturePage()).toPNG())
  app.quit()
})`)
const electron = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const r = spawnSync(electron, [main], { stdio: 'inherit', timeout: 60_000 })
if (r.status !== 0) process.exit(r.status || 1)
console.log(path.resolve(outPng))
