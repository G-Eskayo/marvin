// Evidence and timing for local-first MR Review actions (pipeline review P4/P5, 2026-10-21). Drives the real built app
// against a sandbox HOME and a fake GitHub, never the real one:
//   - a `gh` on the sandbox PATH (~/.agents/bin/gh, where the app looks for the gate) that hands each call to this
//     script's fake GitHub, which answers like GitHub does, after the latency measured for that call on 2026-10-21
//     (~/.claude/logs/gh-calls.jsonl medians plus the gate's start-up);
//   - the REST endpoints the app's conditional reads use (MARVIN_GITHUB_API, localhost only), with real ETags;
//   - a stand-in merge webhook that notes when Approve reaches it and answers "merged" at once, so the client side of
//     Approve is timed on its own (the server side is measured against real GitHub separately);
//   - one fixture PR, #901, with a Decisions section: a sandbox probe, not a real PR's decisions.
// Runs the same steps against any build, so main's build gives "before" and this branch's "after".
// Usage: HOME=<sandbox dir containing "sandbox"> node local_first_evidence.mjs <app-dir> <out-dir> <label> [disagree]
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { createHash } from 'node:crypto'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'
import { approveResponder, wantsStream } from '../webhook-server/merge_progress.js'

const [APP_ARG, OUT, LABEL = 'run', MODE = ''] = process.argv.slice(2)
const HOME = process.env.HOME
if (!APP_ARG || !OUT || !HOME || HOME === '/Users/gileskayo' || !HOME.includes('sandbox')) {
  console.error('usage: HOME=<a sandbox dir, path containing "sandbox"> node local_first_evidence.mjs <app-dir> <out-dir> <label> [disagree]')
  process.exit(1)
}
const APP = path.resolve(APP_ARG)
const DISAGREE = MODE === 'disagree'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
fs.mkdirSync(OUT, { recursive: true })

// ---- latency, ms: 2026-10-21 medians from gh-calls.jsonl (pr list 856, issue list 1798) plus ~400 ms gate start-up;
// the review's 3.45 s for GET+PATCH+POST gives ~1150 per api call. A conditional REST read skips the gate.
const LATENCY = { 'pr list': 1250, 'issue list': 2200, api: 1150, 'pr view': 1000, 'issue view': 1000, rest: 300, other: 500 }

// ---- the fake GitHub ----
const MARVIN = 'G-Eskayo/marvin'
const REPOS = [MARVIN, 'G-Eskayo/clarity-captions', 'G-Eskayo/finance-os', 'G-Eskayo/killer-sudoku', 'G-Eskayo/MechanicGPT', 'G-Eskayo/nourished',
  'G-Eskayo/portfolio', 'G-Eskayo/resume-tailor', 'G-Eskayo/marvin-mobile', 'G-Eskayo/seal', 'G-Eskayo/hermes', 'G-Eskayo/terry', 'G-Eskayo/osint']
const PR_URL = `https://github.com/${MARVIN}/pull/901`
const BODY = `Closes #900

A sandbox fixture for timing local-first actions. Not a real PR.

## Decisions
<!-- marvin:decisions -->
### probe: Which answer should the probe record?
- [ ] Yes
- [ ] No
`
const issues = new Map([[901, { number: 901, title: 'Probe: local-first timing (sandbox fixture)', body: BODY, state: 'open', labels: [], pull_request: {}, comments: 0 }],
  [900, { number: 900, title: 'Probe ticket', body: 'x', state: 'open', labels: [], comments: 0 }]])
const pr = () => ({
  number: 901, title: issues.get(901).title, url: PR_URL, body: issues.get(901).body, state: issues.get(901).state === 'open' ? 'OPEN' : 'MERGED',
  files: [{ path: 'lib/probe.py' }], baseRefName: 'main', headRefName: 'pipeline/g-eskayo/marvin#900', headRefOid: '9'.repeat(40), mergeable: 'MERGEABLE', isDraft: false,
  statusCheckRollup: [{ __typename: 'CheckRun', name: 'Dashboard unit tests', workflowName: 'CI', status: 'COMPLETED', conclusion: 'SUCCESS', startedAt: new Date(Date.now() - 600_000).toISOString(), completedAt: new Date(Date.now() - 500_000).toISOString() }]
})
const pick = (o, fields) => Object.fromEntries(fields.split(',').map((f) => [f, o[f]]))
const etagOf = (v) => `W/"${createHash('sha1').update(JSON.stringify(v)).digest('hex')}"`
const log = [] // { t, kind, what }

function gh(args, input) {
  const a = (f) => args[args.indexOf(f) + 1]
  const cmd = args.slice(0, 2).join(' ')
  if (cmd === 'pr list') {
    const open = a('--repo') === MARVIN && issues.get(901).state === 'open'
    return { kind: 'pr list', out: JSON.stringify(open ? [pick(pr(), a('--json'))] : []) }
  }
  if (cmd === 'issue list') return { kind: 'issue list', out: '[]' }
  if (cmd === 'pr view') return { kind: 'pr view', out: JSON.stringify(pick(pr(), a('--json'))) }
  if (cmd === 'issue view') { const i = issues.get(Number(args[2])) || {}; return { kind: 'issue view', out: JSON.stringify({ number: i.number, title: i.title, body: i.body, labels: i.labels }) } }
  if (args[0] === 'api') {
    const target = args.find((x) => x.startsWith('repos/'))
    const n = Number((target.match(/issues\/(\d+)/) || [])[1])
    if (/\/comments$/.test(target)) { issues.get(n).comments += 1; return { kind: 'api', out: `https://github.com/${MARVIN}/pull/${n}#issuecomment-${Date.now()}\n` } }
    if (args.includes('PATCH')) {
      const sent = JSON.parse(input || '{}').body
      if (!DISAGREE) issues.get(n).body = sent // disagree: GitHub keeps what it had
      const json = JSON.stringify(issues.get(n))
      return { kind: 'api', out: args.includes('--include') ? `HTTP/2.0 200 OK\r\nEtag: ${etagOf(issues.get(n))}\r\nContent-Type: application/json\r\n\r\n${json}` : json }
    }
    return { kind: 'api', out: JSON.stringify(issues.get(n)) }
  }
  return { kind: 'other', out: '{}' }
}

const server = createServer((req, res) => {
  let raw = ''
  req.on('data', (c) => (raw += c))
  req.on('end', async () => {
    const t = Date.now()
    if (req.method === 'POST' && req.url === '/gh') {
      const { args, input } = JSON.parse(raw)
      const r = gh(args, input)
      log.push({ t, kind: r.kind, what: args.join(' ').slice(0, 160) })
      await sleep(LATENCY[r.kind] ?? LATENCY.other)
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ stdout: r.out, code: 0 }))
      return
    }
    const m = req.url.match(/^\/repos\/([^/]+\/[^/]+)\/(issues\/(\d+)|pulls\?state=open)/)
    if (req.method === 'GET' && m) {
      const body = m[3] ? issues.get(Number(m[3])) : (m[1] === MARVIN && issues.get(901).state === 'open' ? [{ number: 901, head: { sha: '9'.repeat(40) }, base: { ref: 'main' } }] : [])
      const etag = etagOf(body)
      const hit = req.headers['if-none-match'] === etag
      log.push({ t, kind: hit ? 'rest 304' : 'rest 200', what: req.url })
      await sleep(LATENCY.rest)
      if (hit) { res.writeHead(304, { ETag: etag }).end(); return }
      res.writeHead(200, { 'Content-Type': 'application/json', ETag: etag }).end(JSON.stringify(body))
      return
    }
    res.writeHead(404).end()
  })
})
const apiPort = await freePort()
await new Promise((r) => server.listen(apiPort, '127.0.0.1', r))

// ---- the sandbox: registry of 13 repos, and the gh shim where the app looks for the gate ----
fs.mkdirSync(path.join(HOME, '.claude', 'boards'), { recursive: true })
fs.writeFileSync(path.join(HOME, '.claude', 'boards', 'registry.json'), JSON.stringify({ boards: REPOS.map((repo) => ({ repo, name: repo.split('/')[1] })) }))
fs.mkdirSync(path.join(HOME, '.agents', 'bin'), { recursive: true })
const SHIM_JS = path.join(HOME, 'gh-shim.mjs')
fs.writeFileSync(SHIM_JS, `import fs from 'node:fs'
const args = process.argv.slice(2)
const i = args.indexOf('--input')
const input = i >= 0 ? fs.readFileSync(args[i + 1], 'utf8') : null
const res = await fetch('http://127.0.0.1:${apiPort}/gh', { method: 'POST', body: JSON.stringify({ args, input }) })
const { stdout, code } = await res.json()
process.stdout.write(stdout)
process.exit(code)
`)
fs.writeFileSync(path.join(HOME, '.agents', 'bin', 'gh'), `#!/bin/sh\nexec "${process.execPath}" "${SHIM_JS}" "$@"\n`, { mode: 0o755 })

// ---- the stand-in merge webhook ----
const marks = {}
const hook = createServer((req, res) => {
  let raw = ''
  req.on('data', (c) => (raw += c))
  req.on('end', async () => {
    if (req.url !== '/approve') { res.writeHead(200, { 'Content-Type': 'application/json' }).end('{}'); return }
    marks.approveReachedWebhook = Date.now()
    const reply = approveResponder(res, { streaming: wantsStream(req.headers.accept) })
    let seq = 0
    const ev = (stage, state) => reply.event({ id: 'probe', seq: ++seq, stage, state, at: Date.now() })
    ev('queued', 'running'); ev('fetching', 'running'); ev('fetching', 'done'); ev('merging', 'running')
    issues.get(901).state = 'closed'
    ev('merging', 'done'); ev('done', 'done')
    reply.result(200, { merged: true, reengaged: false, reason: null })
  })
})
const hookPort = await freePort()
await new Promise((r) => hook.listen(hookPort, '127.0.0.1', r))

// ---- the real app ----
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const port = await freePort()
const env = { ...captureLaunchEnv(process.env), MARVIN_GITHUB_API: `http://127.0.0.1:${apiPort}`, MARVIN_MR_WEBHOOK_URL: `http://127.0.0.1:${hookPort}/approve`, MARVIN_MR_DENY_WEBHOOK_URL: `http://127.0.0.1:${hookPort}/deny` }
delete env.GH_TOKEN
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env, stdio: process.env.LF_TRACE ? ['ignore', 'ignore', fs.openSync(path.join(OUT, `${LABEL}-app.log`), 'w')] : 'ignore' })
let b
for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page
for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
await page.setViewportSize({ width: 1280, height: 900 })

const callsBetween = (a, z) => log.filter((c) => c.t >= a && c.t <= z)
const summary = (calls) => calls.reduce((m, c) => ((m[c.kind] = (m[c.kind] || 0) + 1), m), {})
const result = { label: LABEL, mode: DISAGREE ? 'disagree' : 'agree', latencyMs: LATENCY }
const bootAt = Date.now()
try {
  await sleep(6000)
  await page.locator('button', { hasText: 'MR Review' }).first().click()
  await page.getByText('#901 — Probe', { exact: false }).first().waitFor({ timeout: 120_000 })
  result.bootCalls = summary(callsBetween(bootAt, Date.now()))
  await sleep(3000) // let the boot reads settle
  await page.getByText('#901 — Probe', { exact: false }).first().click()
  await page.locator('[data-question=probe]').waitFor({ timeout: 30_000 })
  await page.locator('[data-question=probe] button', { hasText: 'Yes' }).click()
  const approve = page.locator('button', { hasText: 'Approve & Merge' })

  const t0 = Date.now()
  await page.locator('button', { hasText: 'Submit decisions' }).click()
  if (DISAGREE) {
    await page.locator('[data-correction]').first().waitFor({ timeout: 120_000 })
    result.correctionShownMs = Date.now() - t0
    await sleep(800)
    await page.screenshot({ path: path.join(OUT, `${LABEL}-correction.png`) })
    result.correctionText = await page.locator('[data-correction]').first().innerText()
    result.approveEnabledAfterCorrection = await approve.isEnabled().catch(() => false)
  } else {
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some((x) => x.textContent.includes('Approve & Merge') && !x.disabled), null, { timeout: 180_000, polling: 50 })
    const t1 = Date.now()
    result.decisionsToApproveMs = t1 - t0
    result.decisionsCalls = summary(callsBetween(t0, t1))
    await sleep(600)
    await page.screenshot({ path: path.join(OUT, `${LABEL}-approve-enabled.png`) })
    await sleep(3000)
    const t2 = Date.now()
    await approve.click()
    await page.getByText('#901 — Probe', { exact: false }).first().waitFor({ state: 'detached', timeout: 180_000 }).catch(() => {})
    const t3 = Date.now()
    result.approveClientPreflightMs = (marks.approveReachedWebhook || NaN) - t2
    result.approveToListUpdatedMs = t3 - t2
    result.approveCalls = summary(callsBetween(t2, t3))
    await sleep(500)
    await page.screenshot({ path: path.join(OUT, `${LABEL}-after-approve.png`) })
  }
} catch (e) {
  result.error = String(e?.message || e).split('\n')[0]
  await page.screenshot({ path: path.join(OUT, `${LABEL}-error.png`) }).catch(() => {})
} finally {
  await b.close().catch(() => {})
  proc.kill('SIGTERM')
  server.close()
  hook.close()
}
fs.writeFileSync(path.join(OUT, `${LABEL}-timing.json`), JSON.stringify({ ...result, calls: log.map((c) => ({ ...c, t: c.t - bootAt })) }, null, 2))
console.log(JSON.stringify(result, null, 2))
process.exit(0)
