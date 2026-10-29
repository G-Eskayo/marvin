// Evidence capture for the low-disk refusal (2026-10-28): the built app against a sandbox HOME, a fixed PR list
// (MARVIN_MR_FIXTURE) and a stand-in webhook. The refusal body is not typed by hand: it is what the real mergePr and
// failureResponse produce when the gate's disk check (with first aid that freed too little) refuses. Never the real
// store, webhook or GitHub.
// Usage: HOME=<sandbox> node gate_low_disk_evidence.mjs <out-dir>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'
import { approveResponder, wantsStream } from '../webhook-server/merge_progress.js'
import { mergePr, rebaseAndRetest } from '../webhook-server/merge.js'
import { failureResponse } from '../webhook-server/failure.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT] = process.argv.slice(2)
const HOME = process.env.HOME
if (!OUT || !HOME || !HOME.includes('sandbox')) {
  console.error('usage: HOME=<a sandbox dir, path containing "sandbox"> node gate_low_disk_evidence.mjs <out-dir>')
  process.exit(1)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const GB = 1024 ** 3

// ---- the real refusal: the real gate code, with the disk and first aid stubbed (1.6 GB free, then 1.9 GB) ----
const events = []
let n = 0
const free = async () => (n++ === 0 ? 1.6 * GB : 1.9 * GB)
const aid = async () => ({ ok: true, changed: true, detail: 'freed 300 MiB (aerial videos 300 MiB, caches 0 MiB)' })
const ghExec = async () => ({ stdout: JSON.stringify({ baseRefName: 'main', statusCheckRollup: [] }), stderr: '' })
let body
try {
  await mergePr('https://github.com/G-Eskayo/marvin/pull/600', ghExec, () => {}, () => {},
    async () => ({ gate: true, headRefName: 'pipeline/x', body: '' }),
    (head, run, repo, tests, base, res, sl, progress) => rebaseAndRetest(head, run, repo, tests, base, res, sl, progress, free, aid),
    async () => {}, () => {},
    { uiEvidence: async () => {}, decisions: async () => {}, loadNow: () => ({ id: 'mac-mini-1', load: 1, cores: 4, busy: false }), progress: (stage, state, extra) => events.push([stage, state, extra?.detail]) })
} catch (e) {
  body = failureResponse(e).body
}
console.log('refusal:', body.error)

const pr = {
  repo: 'G-Eskayo/marvin', number: 600, title: 'Pipeline: hand a stale scanner over to the next run', url: 'https://github.com/G-Eskayo/marvin/pull/600',
  body: 'Closes #501\n\nSmall change.', files: [{ path: 'lib/change_600.py' }], baseRefName: 'main', headRefName: 'pipeline/g-eskayo/marvin#501',
  headRefOid: '6'.repeat(40), mergeable: 'MERGEABLE',
  statusCheckRollup: [{ __typename: 'CheckRun', name: 'Dashboard unit tests', workflowName: 'CI', status: 'COMPLETED', conclusion: 'SUCCESS', startedAt: new Date(Date.now() - 600_000).toISOString(), completedAt: new Date(Date.now() - 480_000).toISOString() }]
}
fs.mkdirSync(path.join(HOME, 'fixture'), { recursive: true })
const FIXTURE = path.join(HOME, 'fixture', 'gate-low-disk-prs.json')
fs.writeFileSync(FIXTURE, JSON.stringify([pr]))
fs.mkdirSync(OUT, { recursive: true })

const server = createServer((req, res) => {
  let raw = ''
  req.on('data', (c) => (raw += c))
  req.on('end', async () => {
    const reply = approveResponder(res, { streaming: wantsStream(req.headers.accept) })
    let seq = 0
    for (const [stage, state, detail] of events) {
      reply.event({ id: 'ev-600', seq: ++seq, stage, state, at: Date.now() - 4000 + seq * 300, ...(detail ? { detail } : {}) })
      await sleep(15)
    }
    reply.event({ id: 'ev-600', seq: ++seq, stage: 'rebasing', state: 'failed', at: Date.now(), detail: `${body.code}: ${body.message}` })
    reply.result(500, body)
  })
})
const hookPort = await freePort()
await new Promise((r) => server.listen(hookPort, '127.0.0.1', r))

const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const port = await freePort()
const env = { ...captureLaunchEnv(process.env), MARVIN_MR_FIXTURE: FIXTURE, MARVIN_MR_WEBHOOK_URL: `http://127.0.0.1:${hookPort}/approve`, MARVIN_MR_DENY_WEBHOOK_URL: `http://127.0.0.1:${hookPort}/deny` }
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env, stdio: 'ignore' })
let b
for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page
for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
try {
  for (const width of [1280, 860]) {
    await page.setViewportSize({ width, height: 900 })
    if (width === 1280) {
      await sleep(8000)
      await page.locator('button', { hasText: 'MR Review' }).first().click()
      await sleep(4000)
      const c = page.locator('[role=button]', { hasText: '#600 — ' }).first()
      await c.locator('button', { hasText: 'Approve & Merge' }).click()
      await sleep(2500)
      const open = c.locator('[data-check-progress] button').first()
      if (await open.count()) await open.click()
    }
    await sleep(1500)
    const c = page.locator('[role=button]', { hasText: '#600 — ' }).first()
    await c.scrollIntoViewIfNeeded()
    await c.screenshot({ path: path.join(OUT, `gate-low-disk-refusal-${width}.png`) })
    console.log('shot', width)
  }
} catch (e) {
  await page.screenshot({ path: path.join(OUT, 'debug-window.png') })
  throw e
} finally {
  await b.close()
  proc.kill('SIGTERM')
  server.close()
}
