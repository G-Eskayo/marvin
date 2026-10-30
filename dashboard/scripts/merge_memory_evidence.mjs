// Evidence capture and live check for marvin#940 (merges stop failing on memory pressure): drives the built app against
// a sandbox HOME and a fixed PR list, with two stand-in webhooks that speak the real streamed protocol. The stand-ins
// call the REAL lib/memory_guard.py (its queue under the sandbox HOME, pressure pinned by MARVIN_MEMORY_PRESSURE_LEVEL,
// nothing allocated), the real `forget`, the real `drain`, and the real lib/merge_backup.py for the Mini's own answer.
// Only the merge itself is a stand-in: never the real store, webhook or GitHub. This machine plays the MacBook Pro.
//   1. the Mini is short of memory and the MacBook is on battery: Approve #801 -> "Approved: waiting for memory on the
//      Mac mini"; the ledger says waiting-memory; the Mini's queue holds one copy
//   2. pressure drops: the real drain starts the queued Approve, the Mini merges it, announces, and the dashboard's pass
//      concludes it as merged by the Mini (no second click)
//   3. the MacBook is fit (macOS 27): Approve #802 -> the Mini drops its copy, it merges on this MacBook Pro, and the
//      card says so, with the OS flag
// Usage: HOME=<sandbox> node merge_memory_evidence.mjs <out-dir>
import { chromium } from 'playwright-core'
import { spawn, execFileSync } from 'node:child_process'
import { createServer } from 'node:http'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'
import { MARVIN_REPO } from '../electron/main/mr_repos.js'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'
import { approveResponder, wantsStream } from '../webhook-server/merge_progress.js'

const APP = path.resolve(import.meta.dirname, '..')
const LIB = path.resolve(APP, '..', 'lib')
const PY = fs.existsSync(path.join(os.userInfo().homedir, '.agents', 'venv', 'bin', 'python')) ? path.join(os.userInfo().homedir, '.agents', 'venv', 'bin', 'python') : 'python3'
const [OUT] = process.argv.slice(2)
const HOME = process.env.HOME
if (!OUT || !HOME || HOME === os.userInfo().homedir || !HOME.includes('sandbox')) {
  console.error('usage: HOME=<a sandbox dir, path containing "sandbox"> node merge_memory_evidence.mjs <out-dir>')
  process.exit(1)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const log = (...a) => console.log('[940]', ...a)

// ---- this machine is the MacBook Pro; the Mac mini is the primary ----
const uuid = execFileSync('/usr/sbin/ioreg', ['-d2', '-c', 'IOPlatformExpertDevice'], { encoding: 'utf8' }).split('\n').find((l) => l.includes('IOPlatformUUID')).split('"')[3]
fs.mkdirSync(path.join(HOME, '.claude', 'logs'), { recursive: true })
fs.writeFileSync(path.join(HOME, '.claude', 'marvin-network.json'), JSON.stringify({ devices: {
  'mac-mini-1': { hardware_uuid: 'NOT-THIS-MACHINE', kind: 'desktop', tailscale_hostname: 'mini-sandbox' },
  'macbook-pro-1': { hardware_uuid: uuid, kind: 'laptop', tailscale_hostname: 'book-sandbox' }
} }))

// ---- the PR list ----
const TITLES = { 801: 'Captions: keep the last line on screen for two seconds', 802: 'Health: flag a backup that has not run for a day' }
const prs = Object.entries(TITLES).map(([n, title]) => ({
  repo: MARVIN_REPO, number: Number(n), title, url: `https://github.com/${MARVIN_REPO}/pull/${n}`, state: 'OPEN',
  body: `Closes #${Number(n) - 100}\n\nSmall change.`, files: [{ path: `lib/change_${n}.py` }], baseRefName: 'main', headRefName: `pipeline/${MARVIN_REPO.toLowerCase()}#${Number(n) - 100}`,
  headRefOid: String(n).padStart(40, '0'), mergeable: 'MERGEABLE',
  statusCheckRollup: [{ __typename: 'CheckRun', name: 'Dashboard unit tests', workflowName: 'CI', status: 'COMPLETED', conclusion: 'SUCCESS', startedAt: new Date(Date.now() - 600_000).toISOString(), completedAt: new Date(Date.now() - 480_000).toISOString() }]
}))
fs.mkdirSync(path.join(HOME, 'fixture'), { recursive: true })
const FIXTURE = path.join(HOME, 'fixture', 'merge-memory-prs.json')
const writeFixture = () => fs.writeFileSync(FIXTURE, JSON.stringify(prs))
writeFixture()
fs.mkdirSync(OUT, { recursive: true })

// ---- the real memory guard, in a sandbox HOME of its own where this machine is the Mac mini (the stand-in Mini runs here) ----
const MINI_HOME = path.join(HOME, 'mini-home')
fs.mkdirSync(path.join(MINI_HOME, '.claude'), { recursive: true })
fs.writeFileSync(path.join(MINI_HOME, '.claude', 'marvin-network.json'), JSON.stringify({ devices: {
  'mac-mini-1': { hardware_uuid: uuid, kind: 'desktop', tailscale_hostname: 'mini-sandbox' },
  'macbook-pro-1': { hardware_uuid: 'NOT-THIS-MACHINE', kind: 'laptop', tailscale_hostname: 'book-sandbox' }
} }))
let level = 'warn'
const guard = (args) => {
  try {
    return { rc: 0, out: execFileSync(PY, [path.join(LIB, 'memory_guard.py'), ...args], { env: { ...process.env, HOME: MINI_HOME, MARVIN_MEMORY_PRESSURE_LEVEL: level, HELPER_TAB_QUIET: '1', MARVIN_TEST_SLOT_DIR: path.join(MINI_HOME, 'slot') }, encoding: 'utf8' }) }
  } catch (e) {
    return { rc: e.status, out: String(e.stdout || ''), err: String(e.stderr || '') }
  }
}
const queueFiles = () => { try { return fs.readdirSync(path.join(MINI_HOME, '.claude', 'memory-guard', 'queue')).filter((f) => f.endsWith('.json')) } catch { return [] } }
const miniReady = JSON.parse(execFileSync(PY, [path.join(LIB, 'merge_backup.py'), 'ready', '--repo', MARVIN_REPO], { encoding: 'utf8' }).trim().split('\n').pop())

// ---- two stand-in webhooks ----
const ago = (s) => Date.now() - s * 1000
async function streamMerge(res, accept, n, machineId, holdMs = 0) {
  const reply = approveResponder(res, { streaming: wantsStream(accept) })
  const id = `ev-${n}-${Date.now()}`
  let seq = 0
  const machine = { id: machineId, load: 1.1, cores: 8, busy: false }
  for (const [stage, state, s, extra = {}] of [['queued', 'running', 20], ['fetching', 'running', 19, { machine }], ['fetching', 'done', 18, { estimateMs: 30_000 }], ['rebasing', 'skipped', 18, { detail: "no retest needed: main changed none of this PR's files" }], ['installing', 'skipped', 18], ['tests', 'skipped', 18], ['merging', 'running', 18], ['merging', 'done', 6], ['after', 'running', 6], ['after', 'done', 1], ['done', 'done', 1]]) {
    reply.event({ id, seq: ++seq, stage, state, at: ago(s), ...extra })
    await sleep(stage === 'merging' && state === 'running' ? holdMs : 15)
  }
  reply.result(200, { merged: true, reengaged: false, reason: null })
  prs.find((p) => p.number === n).state = 'MERGED'
  writeFixture()
}
const json = (res, body) => res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(body))
let miniPort, bookPort, refreshPort
let bookFit = { ready: false, why: ['it is on battery (or its power can\'t be read)'], machine: 'macbook-pro-1', os: 'macOS 27.0' }

const mini = createServer((req, res) => {
  let raw = ''
  req.on('data', (c) => (raw += c))
  req.on('end', async () => {
    const route = req.url.split('?')[0]
    if (route === '/merge-ready') return json(res, { ...miniReady, ready: false, why: ['its memory is under pressure'] })
    if (route === '/merge-forget') {
      const r = guard(['forget', '--key', `merge:${JSON.parse(raw).pr_url}`])
      log('mini /merge-forget ->', r.out.trim())
      return json(res, JSON.parse(r.out.trim()))
    }
    if (req.method !== 'POST' || route !== '/approve') return res.writeHead(404).end()
    const body = JSON.parse(raw || '{}')
    const n = Number(String(body.pr_url).split('/').pop())
    log(`mini /approve #${n} by ${body.by || 'dashboard'} at pressure ${level}`)
    // the real check, queueing this same Approve as a POST back to this stand-in (what merge.js memoryGuardCheck does)
    const curl = ['/usr/bin/curl', '-sS', '-X', 'POST', '-H', 'Content-Type: application/json', '--data', JSON.stringify({ pr_url: body.pr_url, by: 'memory-queue' }), `http://127.0.0.1:${miniPort}/approve`]
    const r = guard(['check', '--what', `PR #${n}`, '--key', `merge:${body.pr_url}`, '--', ...curl])
    if (r.rc === 3) {
      const message = r.err.trim().split('\n').pop()
      log('mini refused for memory and queued it:', message)
      return approveResponder(res, { streaming: wantsStream(req.headers.accept) }).result(500, { merged: false, code: 'MEMORY_PRESSURE', stage: 'gate', action: 'retry', retryable: false, message, error: `MEMORY_PRESSURE at gate: ${message}` })
    }
    await streamMerge(res, req.headers.accept, n, 'mac-mini-1')
    log(`mini merged #${n}`)
    if (body.by === 'memory-queue') {   // what index.js does at the end of a queued run: tell the dashboards
      await fetch(`http://127.0.0.1:${refreshPort}/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topics: ['merge-host'], source: 'merge-host-up', machine: 'mac-mini-1' }) })
      log('mini announced: memory-queue run finished')
    }
  })
})
const book = createServer((req, res) => {
  let raw = ''
  req.on('data', (c) => (raw += c))
  req.on('end', async () => {
    const route = req.url.split('?')[0]
    if (route === '/merge-ready') { log('book /merge-ready ->', JSON.stringify(bookFit)); return json(res, bookFit) }
    if (req.method !== 'POST' || route !== '/approve') return res.writeHead(404).end()
    const n = Number(String(JSON.parse(raw || '{}').pr_url).split('/').pop())
    log(`book /approve #${n}`)
    await streamMerge(res, req.headers.accept, n, 'macbook-pro-1', 6000)   // long enough to see the card mid-merge
  })
})
miniPort = await freePort()
bookPort = await freePort()
refreshPort = await freePort()
await new Promise((r) => mini.listen(miniPort, '127.0.0.1', r))
await new Promise((r) => book.listen(bookPort, '127.0.0.1', r))

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
  await c.screenshot({ path: path.join(OUT, `ticket-940-${name}.png`) })
  log('shot', name)
}
const ledger = () => JSON.parse(fs.readFileSync(path.join(HOME, '.claude', 'logs', 'approvals.json'), 'utf8')).approvals.map((a) => `#${a.number ?? a.url.split('/').pop()} ${a.outcome} on ${a.machine}${a.reason ? ` (${a.reason.slice(0, 80)})` : ''}`)
let failed = false
const check = (ok, what) => { log(ok ? 'PASS' : 'FAIL', what); if (!ok) failed = true }
try {
  await page.locator('button', { hasText: 'MR Review' }).first().click()
  await sleep(4000)

  // 1. short of memory, the MacBook on battery: waits on the Mini
  await card(801).locator('button', { hasText: 'Approve & Merge' }).click()
  await sleep(3000)
  await shot(801, 'waiting-for-memory')
  check((await card(801).innerText()).includes('Approved: waiting for memory on the Mac mini'), 'card 801 says waiting for memory on the Mac mini')
  check(queueFiles().length === 1, `the Mini's queue holds one copy (${queueFiles().length})`)
  log('ledger', ledger())

  // 2. pressure drops: the real drain starts the queued Approve (one item), the Mini merges and announces
  level = 'normal'
  const d = guard(['drain'])
  log('drain ->', d.out.trim())
  await sleep(6000)
  check(prs.find((p) => p.number === 801).state === 'MERGED', '801 merged by the Mini\'s own queue, no second click')
  check(queueFiles().length === 0, 'the queue is empty')
  log('ledger', ledger())
  check(ledger().some((l) => l.startsWith('#801 merged on mac-mini-1')), 'the ledger: 801 merged on the Mac mini')
  await page.screenshot({ path: path.join(OUT, 'ticket-940-window-after-pressure-dropped.png') })

  // 3. short of memory again; this time the MacBook is fit (and on macOS 27)
  level = 'warn'
  bookFit = { ready: true, why: [], machine: 'macbook-pro-1', os: 'macOS 27.0' }
  await card(802).locator('button', { hasText: 'Approve & Merge' }).click()
  await sleep(2500)
  await shot(802, 'merging-on-the-macbook')
  check((await card(802).innerText()).includes("The Mac mini's memory is under pressure, merging on this MacBook Pro instead."), 'card 802 says it is merging on this MacBook Pro instead')
  await sleep(6000)   // the merge ends; a merged PR leaves the list
  check(queueFiles().length === 0, 'the Mini dropped its copy: nothing left to merge it twice')
  log('ledger', ledger())
  check(ledger().some((l) => l.startsWith('#802 merged on macbook-pro-1')), 'the ledger: 802 merged on the MacBook Pro')
} finally {
  await b.close()
  proc.kill('SIGTERM')   // the app this script started
  mini.close()
  book.close()
}
log(failed ? 'SOME CHECKS FAILED' : 'all checks passed')
process.exit(failed ? 1 : 0)
