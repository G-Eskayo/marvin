// Evidence capture for marvin#762 (Approve works when the Mac mini is down): drives the built app against a sandbox
// HOME, a fixed PR list (MARVIN_MR_FIXTURE), a "Mac mini" webhook URL nothing listens on, and a stand-in for this
// Mac's webhook (MARVIN_MR_LOCAL_WEBHOOK_URL) that speaks the real streamed protocol. Never the real store, webhook or
// GitHub. The sandbox registry makes this machine the MacBook Pro and names the Mac mini as the primary.
//   1. both down: Approve on #702 -> queued, said plainly
//   2. this Mac's webhook comes up: Approve on #701 -> fails over, "The Mac mini is offline, merging on this MacBook Pro instead."
//   3. the merge-host trigger (what a webhook sends when it starts) -> #702 is retried by itself and merges
// Usage: HOME=<sandbox> node merge_failover_evidence.mjs <out-dir>
import { chromium } from 'playwright-core'
import { spawn, execFileSync } from 'node:child_process'
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
  console.error('usage: HOME=<a sandbox dir, path containing "sandbox"> node merge_failover_evidence.mjs <out-dir>')
  process.exit(1)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ---- this machine is the MacBook Pro; the Mac mini is the primary ----
const uuid = execFileSync('/usr/sbin/ioreg', ['-d2', '-c', 'IOPlatformExpertDevice'], { encoding: 'utf8' }).split('\n').find((l) => l.includes('IOPlatformUUID')).split('"')[3]
fs.mkdirSync(path.join(HOME, '.claude', 'logs'), { recursive: true })
fs.writeFileSync(path.join(HOME, '.claude', 'marvin-network.json'), JSON.stringify({ devices: {
  'mac-mini-1': { hardware_uuid: 'NOT-THIS-MACHINE', kind: 'desktop', tailscale_hostname: 'mini-sandbox' },
  'macbook-pro-1': { hardware_uuid: uuid, kind: 'laptop', tailscale_hostname: 'book-sandbox' }
} }))

// ---- the PR list ----
const TITLES = { 701: 'Health: flag a backup that has not run for a day', 702: 'Docs: search finds words inside PDF files' }
const prs = Object.entries(TITLES).map(([n, title]) => ({
  repo: 'G-Eskayo/marvin', number: Number(n), title, url: `https://github.com/G-Eskayo/marvin/pull/${n}`,
  body: `Closes #${Number(n) - 100}\n\nSmall change.`, files: [{ path: `lib/change_${n}.py` }], baseRefName: 'main', headRefName: `pipeline/g-eskayo/marvin#${Number(n) - 100}`,
  headRefOid: String(n).padStart(40, '0'), mergeable: 'MERGEABLE',
  statusCheckRollup: [{ __typename: 'CheckRun', name: 'Dashboard unit tests', workflowName: 'CI', status: 'COMPLETED', conclusion: 'SUCCESS', startedAt: new Date(Date.now() - 600_000).toISOString(), completedAt: new Date(Date.now() - 480_000).toISOString() }]
}))
fs.mkdirSync(path.join(HOME, 'fixture'), { recursive: true })
const FIXTURE = path.join(HOME, 'fixture', 'merge-failover-prs.json')
fs.writeFileSync(FIXTURE, JSON.stringify(prs))
fs.mkdirSync(OUT, { recursive: true })

// ---- the stand-in for this MacBook's webhook (not listening until step 2) ----
const book = { id: 'macbook-pro-1', load: 1.2, cores: 8, busy: false }
const ago = (s) => Date.now() - s * 1000
const SCENARIOS = {
  701: { events: [['queued', 'running', 40], ['fetching', 'running', 38, { machine: book }], ['fetching', 'done', 34, { estimateMs: 240_000 }], ['rebasing', 'running', 34], ['rebasing', 'done', 28], ['installing', 'running', 28], ['installing', 'done', 12], ['tests', 'running', 12, { detail: 'Python', count: { done: 40, total: 100, unit: '%' } }]], end: 'hold' },
  702: { events: [['queued', 'running', 30], ['fetching', 'running', 28, { machine: book }], ['fetching', 'done', 24, { estimateMs: 45_000 }], ['rebasing', 'skipped', 24, { detail: "no retest needed: main changed none of this PR's files" }], ['installing', 'skipped', 24], ['tests', 'skipped', 24], ['merging', 'running', 24], ['merging', 'done', 12], ['after', 'running', 12], ['after', 'done', 2], ['done', 'done', 2]], end: { status: 200, body: { merged: true, reengaged: false, reason: null } } }
}
const held = []
const server = createServer((req, res) => {
  let raw = ''
  req.on('data', (c) => (raw += c))
  req.on('end', async () => {
    const n = Number((JSON.parse(raw || '{}').pr_url || '').split('/').pop())
    const sc = SCENARIOS[n]
    if (!sc) { res.writeHead(404).end(); return }
    const reply = approveResponder(res, { streaming: wantsStream(req.headers.accept) })
    let seq = 0
    const id = `ev-${n}-${Date.now()}`
    for (const [stage, state, secsAgo, extra = {}] of sc.events) { reply.event({ id, seq: ++seq, stage, state, at: ago(secsAgo), ...extra }); await sleep(15) }
    if (sc.end === 'hold') held.push(res)
    else reply.result(sc.end.status, sc.end.body)
  })
})
const bookPort = await freePort()
const miniPort = await freePort() // nothing ever listens here: the Mac mini's webhook is down
const refreshPort = await freePort()

// ---- the real app ----
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const port = await freePort()
const env = { ...captureLaunchEnv(process.env), MARVIN_DASHBOARD_REFRESH_PORT: String(refreshPort), MARVIN_MR_FIXTURE: FIXTURE,
  MARVIN_MR_WEBHOOK_URL: `http://127.0.0.1:${miniPort}/approve`, MARVIN_MR_LOCAL_WEBHOOK_URL: `http://127.0.0.1:${bookPort}/approve`, MARVIN_MR_DENY_WEBHOOK_URL: `http://127.0.0.1:${bookPort}/deny` }
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env, stdio: 'ignore' })
let b
for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page
for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
await page.setViewportSize({ width: 1280, height: 900 })
await sleep(8000)
const card = (n) => page.locator('[role=button]', { hasText: `#${n} — ` }).first()
const shot = async (n, name) => {
  const c = card(n)
  await c.scrollIntoViewIfNeeded()
  await sleep(1500)
  await c.screenshot({ path: path.join(OUT, `ticket-762-${name}.png`) })
  console.log('shot', name)
}
try {
  await page.locator('button', { hasText: 'MR Review' }).first().click()
  await sleep(4000)
  // 1. both down
  await card(702).locator('button', { hasText: 'Approve & Merge' }).click()
  await sleep(2500)
  await shot(702, 'both-down-queued')
  // 2. this Mac's webhook is up; the Mini is still down
  await new Promise((r) => server.listen(bookPort, '127.0.0.1', r))
  await card(701).locator('button', { hasText: 'Approve & Merge' }).click()
  await sleep(2500)
  await shot(701, 'failover-merging')
  // 3. the trigger a webhook sends when it starts: the saved approval of #702 merges by itself
  await fetch(`http://127.0.0.1:${refreshPort}/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topics: ['merge-host'], source: 'merge-host-up', machine: 'macbook-pro-1' }) })
  await sleep(3000)
  await page.screenshot({ path: path.join(OUT, 'ticket-762-window-after-retry.png') })
  console.log('shot window-after-retry')
  console.log('ledger', fs.readFileSync(path.join(HOME, '.claude', 'logs', 'approvals.json'), 'utf8'))
} finally {
  for (const res of held) res.socket?.destroy()
  await b.close()
  proc.kill('SIGTERM')
  server.close()
}
