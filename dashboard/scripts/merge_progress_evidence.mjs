// Evidence capture for marvin#568 (merge progress on MR Review cards): drives the built app against a sandbox HOME, a
// fixed PR list (MARVIN_MR_FIXTURE) and a stand-in merge webhook that speaks the real streamed protocol
// (webhook-server/merge_progress.js approveResponder), so the real UI receives real stage events. Never the real store,
// webhook or GitHub. One PR per state; each card is clicked (Approve & Merge), fed its events, and shot.
// Usage: HOME=<sandbox> node merge_progress_evidence.mjs <out-dir>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'
import { approveResponder, wantsStream } from '../webhook-server/merge_progress.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT] = process.argv.slice(2)
const HOME = process.env.HOME
if (!OUT || !HOME || HOME === '/Users/gileskayo' || !HOME.includes('sandbox')) {
  console.error('usage: HOME=<a sandbox dir, path containing "sandbox"> node merge_progress_evidence.mjs <out-dir>')
  process.exit(1)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ---- the PR list ----
const TITLES = {
  601: 'Activity: show which Mac claimed each ticket',
  602: 'Health: flag a backup that has not run for a day',
  603: 'Docs: search finds words inside PDF files',
  604: 'Boards: keep the column order after a refresh',
  605: 'MR Review: remember the open/merged toggle',
  606: 'Proposals: sort by how much each one unlocks'
}
const prs = Object.entries(TITLES).map(([n, title]) => ({
  repo: 'G-Eskayo/marvin', number: Number(n), title, url: `https://github.com/G-Eskayo/marvin/pull/${n}`,
  body: `Closes #${Number(n) - 100}\n\nSmall change.`, files: [{ path: `lib/change_${n}.py` }], baseRefName: 'main', headRefName: `pipeline/g-eskayo/marvin#${Number(n) - 100}`,
  headRefOid: String(n).padStart(40, '0'), mergeable: 'MERGEABLE',
  statusCheckRollup: [{ __typename: 'CheckRun', name: 'Dashboard unit tests', workflowName: 'CI', status: 'COMPLETED', conclusion: 'SUCCESS', startedAt: new Date(Date.now() - 600_000).toISOString(), completedAt: new Date(Date.now() - 480_000).toISOString() }]
}))
fs.mkdirSync(path.join(HOME, 'fixture'), { recursive: true })
const FIXTURE = path.join(HOME, 'fixture', 'merge-progress-prs.json')
fs.writeFileSync(FIXTURE, JSON.stringify(prs))
fs.mkdirSync(OUT, { recursive: true })

// ---- the stand-in webhook: each PR's scenario, stepped by this script ----
const idle = { id: 'mac-mini-1', load: 2.1, cores: 10, busy: false }
const busy = { id: 'mac-mini-1', load: 9.4, cores: 10, busy: true, top: 'engine test' }
const ago = (s) => Date.now() - s * 1000
const upToTests = (machineAtTests) => [
  ['queued', 'running', 118], ['fetching', 'running', 116, { machine: idle }], ['fetching', 'done', 112, { estimateMs: 185_000 }],
  ['rebasing', 'running', 112], ['rebasing', 'done', 104], ['installing', 'running', 104], ['installing', 'done', 74],
  ['tests', 'running', 74, { detail: 'Python', ...(machineAtTests ? { machine: machineAtTests } : {}) }], ['tests', 'running', 40, { detail: 'Python', count: { done: 100, total: 100, unit: '%' } }],
  ['tests', 'running', 38, { detail: 'Dashboard', count: { done: 120, total: 183, unit: 'files' } }]
]
const SCENARIOS = {
  601: { events: [['queued', 'running', 3, { detail: '1 merge ahead' }]], end: 'hold' },
  602: { events: upToTests(idle), end: 'hold' },
  603: { events: upToTests(busy), end: 'hold' },
  604: { events: [...upToTests(idle), ['tests', 'failed', 5, { detail: 'GATE_TESTS_FAILED: 2 failing test(s)' }]], end: { status: 200, body: { merged: false, reengaged: true, code: 'GATE_TESTS_FAILED', stage: 'gate', reason: '2 tests fail after rebasing onto main: test_backup_age, test_column_order. Sent back to its ticket.' } } },
  605: { events: upToTests(idle).slice(0, 8), end: 'drop' },
  606: { events: [['queued', 'running', 50], ['fetching', 'running', 48, { machine: idle }], ['fetching', 'done', 44, { estimateMs: 45_000 }], ['rebasing', 'skipped', 44, { detail: "no retest needed: main changed none of this PR's files" }], ['installing', 'skipped', 44], ['tests', 'skipped', 44], ['merging', 'running', 44], ['merging', 'done', 30], ['after', 'running', 30], ['after', 'done', 8], ['done', 'done', 8]], end: { status: 200, body: { merged: true, reengaged: false, reason: null } } }
}
const held = new Map()
const server = createServer((req, res) => {
  let raw = ''
  req.on('data', (c) => (raw += c))
  req.on('end', async () => {
    const url = JSON.parse(raw || '{}').pr_url || ''
    const n = Number(url.split('/').pop())
    const sc = SCENARIOS[n]
    if (!sc) { res.writeHead(404).end(); return }
    const reply = approveResponder(res, { streaming: wantsStream(req.headers.accept) })
    let seq = 0
    for (const [stage, state, secsAgo, extra = {}] of sc.events) {
      reply.event({ id: `ev-${n}`, seq: ++seq, stage, state, at: ago(secsAgo), ...extra })
      await sleep(15)
    }
    if (sc.end === 'hold') held.set(n, res)
    else if (sc.end === 'drop') { await sleep(300); res.socket.destroy() } // the webhook restarting mid-merge
    else reply.result(sc.end.status, sc.end.body)
  })
})
const hookPort = await freePort()
await new Promise((r) => server.listen(hookPort, '127.0.0.1', r))

// ---- the real app ----
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const port = await freePort()
const env = { ...captureLaunchEnv(process.env), MARVIN_MR_FIXTURE: FIXTURE, MARVIN_MR_WEBHOOK_URL: `http://127.0.0.1:${hookPort}/approve`, MARVIN_MR_DENY_WEBHOOK_URL: `http://127.0.0.1:${hookPort}/deny` }
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env, stdio: 'ignore' })
let b
for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page
for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
await page.setViewportSize({ width: 1280, height: 900 })
await sleep(8000)
const card = (n) => page.locator('[role=button]', { hasText: `#${n} — ` }).first()
const shot = async (n, name, { open = false } = {}) => {
  const c = card(n)
  await c.scrollIntoViewIfNeeded()
  if (open) await c.locator('[data-check-progress] button').first().click()
  await sleep(1500)
  await c.screenshot({ path: path.join(OUT, `ticket-568-${name}.png`) })
  console.log('shot', name)
}
try {
  await page.locator('button', { hasText: 'MR Review' }).first().click()
  await sleep(4000)
  for (const n of Object.keys(SCENARIOS)) {
    await card(n).locator('button', { hasText: 'Approve & Merge' }).click()
    await sleep(700)
  }
  await sleep(2500)
  await shot(601, 'queued', { open: true })
  await shot(602, 'mid-tests', { open: true })
  await shot(603, 'busy-machine')
  await shot(604, 'failed-stage', { open: true })
  await shot(605, 'interrupted', { open: true })
  await shot(606, 'done', { open: true })
  await page.screenshot({ path: path.join(OUT, 'ticket-568-window.png') })
  console.log('shot window')
} finally {
  for (const res of held.values()) res.socket?.destroy()
  await b.close()
  proc.kill('SIGTERM')
  server.close()
}
