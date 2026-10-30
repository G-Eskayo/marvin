// Evidence capture for marvin#838 (the merge motion in the real MR Review): drives the built app against a sandbox
// HOME, a fixed PR list (MARVIN_MR_FIXTURE) and a stand-in merge server that answers the side reads (history,
// auto-merge shadow, rebase status) with nothing. Merges are staged the way a webhook reports them: stage events on
// the app's own refresh port (topic "merge"), so the app adopts each merge, shows its progress, and pushes "merged"
// when the last stage is done. Then the PR is dropped from the fixture and the list is pinged, as GitHub would.
// Never the real store, webhook or GitHub. Each scene runs in a fresh app, normal motion and Reduce Motion, recorded
// with the page's own screencast (real time, not seeked) and joined side by side into one GIF per scene.
// Usage: HOME=<sandbox dir> node merge_motion_evidence.mjs <out-dir> [scene ...]
import { chromium } from 'playwright-core'
import { spawn, execFileSync } from 'node:child_process'
import { createServer } from 'node:http'
import path from 'node:path'
import fs from 'node:fs'
import os from 'node:os'
import { MARVIN_REPO } from '../electron/main/mr_repos.js'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT, ...ONLY] = process.argv.slice(2)
const HOME = process.env.HOME
if (!OUT || !HOME || HOME === os.userInfo().homedir || !HOME.includes('sandbox')) {
  console.error('usage: HOME=<a sandbox dir, path containing "sandbox"> node merge_motion_evidence.mjs <out-dir> [scene ...]')
  process.exit(1)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
fs.mkdirSync(OUT, { recursive: true })
const LOGS = path.join(HOME, '.claude', 'logs')
fs.mkdirSync(LOGS, { recursive: true })
fs.mkdirSync(path.join(HOME, 'fixture'), { recursive: true })
const FIXTURE = path.join(HOME, 'fixture', 'merge-motion-prs.json')
const HISTORY = path.join(LOGS, 'mr-history.json')

// ---- the PR list ----
const TITLES = {
  801: 'Docs: search inside PDFs', 802: 'Vitals: disk headroom per machine', 803: 'bin/gh refuses unreadable Decisions',
  804: 'Activity: helper tabs show their group colour', 805: 'Support: link opens the right check', 806: 'Usage: hourly budget line',
  807: 'Board: stale claims released after 6 h', 808: 'MR Review: images pinned by full SHA', 809: 'Home: next-up queue shows the owner first',
  810: 'Vitals: battery health on the laptop', 811: 'Mobile: offline banner on the MR list', 812: 'Docs: keep your place when you go back'
}
const url = (n) => `https://github.com/${MARVIN_REPO}/pull/${n}`
const pr = (n) => ({
  repo: MARVIN_REPO, number: n, title: TITLES[n], url: url(n),
  body: `Closes #${n - 100}\n\nSmall change.`, files: [{ path: `lib/change_${n}.py` }], baseRefName: 'main', headRefName: `pipeline/${MARVIN_REPO.toLowerCase()}#${n - 100}`,
  headRefOid: String(n).padStart(40, '0'), mergeable: 'MERGEABLE',
  statusCheckRollup: [{ __typename: 'CheckRun', name: 'Dashboard unit tests', workflowName: 'CI', status: 'COMPLETED', conclusion: 'SUCCESS', startedAt: new Date(Date.now() - 600_000).toISOString(), completedAt: new Date(Date.now() - 480_000).toISOString() }]
})
let open = []
const writeList = () => fs.writeFileSync(FIXTURE, JSON.stringify(open.map(pr)))
const mergedRow = (n, title, minsAgo) => ({ url: url(n), number: n, title, repo: MARVIN_REPO, mergedAt: new Date(Date.now() - minsAgo * 60_000).toISOString() })
const writeHistory = (rows) => fs.writeFileSync(HISTORY, JSON.stringify({ merged: rows, updatedAt: Date.now(), history: { merges: rows.map((r) => ({ pr_url: r.url, by: 'you' })), refusals: [] }, open: [] }))

// ---- the stand-in merge server: every side read answers "nothing to report" ----
const server = createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'application/json' })
  res.end(req.url.startsWith('/merge-history') ? JSON.stringify({ merges: [], refusals: [] }) : '{}')
})
const srvPort = await freePort()
await new Promise((r) => server.listen(srvPort, '127.0.0.1', r))

// ---- the real app, fresh for each scene ----
const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
async function launch({ reduced }) {
  const port = await freePort(), refreshPort = await freePort()
  const env = { ...captureLaunchEnv(process.env), MARVIN_DASHBOARD_REFRESH_PORT: String(refreshPort), MARVIN_MR_FIXTURE: FIXTURE,
    MARVIN_MR_WEBHOOK_URL: `http://127.0.0.1:${srvPort}/approve`, MARVIN_MR_LOCAL_WEBHOOK_URL: `http://127.0.0.1:${srvPort}/approve` }
  const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env, stdio: 'ignore' })
  let b
  for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
  let page
  for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
  await page.setViewportSize({ width: 1180, height: 820 })
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: reduced ? 'reduce' : 'no-preference' }] })
  // Any key skips the boot sequence (BootSequence.jsx), once it is playing: keep pressing until it has gone.
  await page.locator('main').waitFor({ timeout: 30000 })
  for (let i = 0; i < 80; i++) {
    if (!(await page.locator('.boot-root').count())) { if (i > 4) break } else await page.keyboard.press('Escape')
    await sleep(300)
  }
  await sleep(1500)
  const ping = (payload) => fetch(`http://127.0.0.1:${refreshPort}/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  return { b, proc, page, cdp, ping }
}

// A merge reported stage by stage, as the webhook does; `fail` ends it with GitHub refusing at "Merging on GitHub".
async function merge(app, n, { stepMs = 260, fail = null } = {}) {
  const id = `ev-${n}-${Date.now()}`
  const stages = [['queued', 'running'], ['fetching', 'running'], ['rebasing', 'running'], ['installing', 'running'], ['tests', 'running'], ['merging', 'running']]
  const tail = fail ? [['merging', 'failed', { detail: fail }]] : [['after', 'running'], ['done', 'done']]
  let seq = 0
  for (const [stage, state, extra = {}] of [...stages, ...tail]) {
    await app.ping({ topics: ['merge'], merge: { url: url(n), event: { id, seq: ++seq, stage, state, at: Date.now(), ...extra } } })
    await sleep(stepMs)
  }
}
// GitHub's list catches up: the merged PRs drop out of it, and the list is told.
async function drop(app, ...ns) { open = open.filter((n) => !ns.includes(n)); writeList(); await app.ping({ topics: ['mr'], source: 'evidence' }) }
async function add(app, at, ...ns) { open.splice(at, 0, ...ns); writeList(); await app.ping({ topics: ['mr'], source: 'evidence' }) }
const card = (page, n) => page.locator('[data-motion-slot]', { hasText: `#${n} — ` }).first()
const scroller = (page) => page.locator('main')

async function openReview(page) {
  await page.locator('button', { hasText: 'MR Review' }).first().click()
  await page.locator('[data-motion-slot]').first().waitFor({ timeout: 20000 })
  await sleep(1200)
}

// ---- the screencast: every frame the page paints, with its time, joined by ffmpeg ----
async function record(cdp, dir, fn) {
  fs.rmSync(dir, { recursive: true, force: true })
  fs.mkdirSync(dir, { recursive: true })
  const frames = []
  const onFrame = async ({ data, metadata, sessionId }) => {
    const file = path.join(dir, `f${String(frames.length).padStart(5, '0')}.jpg`)
    frames.push({ file, ts: metadata.timestamp })
    fs.writeFileSync(file, Buffer.from(data, 'base64'))
    await cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {})
  }
  cdp.on('Page.screencastFrame', onFrame)
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 85, everyNthFrame: 1 })
  const t0 = Date.now() / 1000
  await fn()
  await sleep(1500)
  await cdp.send('Page.stopScreencast')
  cdp.off('Page.screencastFrame', onFrame)
  // Hold the first frame from the start, and the last one for a second at the end.
  const lines = []
  frames.forEach((f, i) => {
    const next = frames[i + 1]?.ts ?? f.ts + 1
    lines.push(`file '${f.file}'`, `duration ${Math.max(0.001, next - f.ts).toFixed(3)}`)
  })
  if (frames.length) lines.push(`file '${frames.at(-1).file}'`)
  fs.writeFileSync(path.join(dir, 'list.txt'), lines.join('\n'))
  const mp4 = `${dir}.mp4`
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', path.join(dir, 'list.txt'), '-vf', 'fps=25,scale=720:-2:flags=lanczos', '-pix_fmt', 'yuv420p', mp4])
  fs.rmSync(dir, { recursive: true, force: true })
  return { mp4, frames: frames.length, seconds: frames.length ? frames.at(-1).ts - frames[0].ts : 0, t0 }
}

// Normal | Reduce Motion, side by side, as one GIF (and the MP4 pair kept for the PR's "how to read" note).
function sideBySide(name, normal, reduced) {
  const gif = path.join(OUT, `${name}.gif`)
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', normal, '-i', reduced, '-filter_complex',
    '[0:v][1:v]hstack=inputs=2,fps=20,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle', gif])
  return gif
}

// ---- the scenes ----
const BASE = [801, 802, 803, 804, 805, 806]
const SCENES = {
  // Leaving Open: progress with the blue border, the bar turns into the check, then the sweep with its light bar.
  single: { list: BASE, async run(app) { await openReview(app.page); await merge(app, 802); await sleep(200); await drop(app, 802); await sleep(2400) } },
  // Three confirmed out of list order: one at a time, in the order GitHub confirmed them (803, then 801, then 802).
  queue: { list: BASE, async run(app) {
    await openReview(app.page)
    await Promise.all([merge(app, 803, { stepMs: 120 }), sleep(300).then(() => merge(app, 801, { stepMs: 120 })), sleep(600).then(() => merge(app, 802, { stepMs: 120 }))])
    await drop(app, 801, 802, 803)
    await sleep(5200)
  } },
  // A new MR comes into Open: the space opens where it belongs (third), then it sweeps in.
  incoming: { list: BASE, async run(app) { await openReview(app.page); await sleep(400); await add(app, 2, 810); await sleep(2400) } },
  // GitHub refuses: nothing moves, the existing notice says why, and that it stays in Open.
  refused: { list: BASE, async run(app) { await openReview(app.page); await merge(app, 802, { fail: 'GitHub refused the merge: a required check failed.' }); await sleep(2200) } },
  // Scrolled down: a merge above you and two MRs coming in above you at once change the list out of view; your place
  // holds and a chip says each, one at a time. Then a card on screen merges as usual.
  scrolled: { list: [801, 802, 803, 804, 805, 806, 807, 808, 809], async run(app) {
    await openReview(app.page)
    await card(app.page, 807).evaluate((el) => el.scrollIntoView({ block: 'start' }))
    await sleep(800)
    await merge(app, 801, { stepMs: 100 }); await drop(app, 801)
    await sleep(900)
    await add(app, 0, 811, 812)
    await sleep(4200)
    await merge(app, 808, { stepMs: 160 }); await drop(app, 808)
    await sleep(2600)
  } },
  // Inside the MR when it merges: the merged line, then Back plays the sweep.
  detail: { list: BASE, async run(app) {
    await openReview(app.page)
    await card(app.page, 802).locator('p.font-mono').first().click()
    await sleep(900)
    await merge(app, 802, { stepMs: 160 }); await drop(app, 802)
    await sleep(2200)
    await app.page.locator('button', { hasText: '← Back to MR Review' }).click()
    await sleep(2800)
  } },
  // On the Merged tab when a merge arrives: a space opens at the top and the row sweeps in, left to right. It
  // reverts #777, which gets the grey "reverted by #802" pill.
  arrive: { list: BASE, history: true, async run(app) {
    await openReview(app.page)
    await app.page.locator('[aria-label="Which PRs"] button', { hasText: 'Merged' }).click()
    await sleep(2500)
    writeHistory([mergedRow(802, 'Revert "Board: parity check per project"', 0), ...HISTORY_ROWS])
    await merge(app, 802, { stepMs: 60 })
    await sleep(2600)
  } },
  // Away on another tab while two merge: back on Open, just the result and the count.
  away: { list: BASE, async run(app) {
    await openReview(app.page)
    await app.page.locator('button', { hasText: 'Docs' }).first().click()
    await sleep(800)
    await merge(app, 803, { stepMs: 60 }); await merge(app, 805, { stepMs: 60 }); await drop(app, 803, 805)
    await sleep(800)
    await openReview(app.page)
    await sleep(1500)
  } }
}
const HISTORY_ROWS = [mergedRow(779, 'Gate: low disk refuses merges', 80), mergedRow(778, 'helper-tab: labelled WezTerm tabs', 140), mergedRow(777, 'Board: parity check per project', 200), mergedRow(776, 'macOS screenshot capture', 260)]

// Light-bar looks for the Decision: the built one (leading edge), both edges, or none. Normal motion only.
const LOOKS = { 'lightbar-both': { lead: 1, trail: 1 }, 'lightbar-none': { lead: 0, trail: 0 } }

const results = []
try {
  for (const [name, sc] of Object.entries(SCENES)) {
    if (ONLY.length && !ONLY.includes(name)) continue
    const mp4s = []
    for (const reduced of [false, true]) {
      open = sc.list.slice(); writeList(); writeHistory(sc.history ? HISTORY_ROWS : [])
      const app = await launch({ reduced })
      try {
        mp4s.push((await record(app.cdp, path.join(OUT, `${name}-${reduced ? 'reduced' : 'normal'}`), () => sc.run(app))).mp4)
      } finally { await app.b.close().catch(() => {}); app.proc.kill('SIGTERM') }
      await sleep(1500)
    }
    results.push(sideBySide(name, ...mp4s))
    console.log('scene', name, results.at(-1))
  }
  for (const [name, look] of Object.entries(LOOKS)) {
    if (ONLY.length && !ONLY.includes(name)) continue
    open = BASE.slice(); writeList(); writeHistory([])
    const app = await launch({ reduced: false })
    try {
      await app.page.evaluate(({ lead, trail }) => { document.documentElement.style.setProperty('--mm-lightbar-lead', lead); document.documentElement.style.setProperty('--mm-lightbar-trail', trail) }, look)
      const r = await record(app.cdp, path.join(OUT, name), () => SCENES.single.run(app))
      const gif = path.join(OUT, `${name}.gif`)
      execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', r.mp4, '-filter_complex', 'fps=20,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle', gif])
      results.push(gif)
      console.log('look', name, gif)
    } finally { await app.b.close().catch(() => {}); app.proc.kill('SIGTERM') }
    await sleep(1500)
  }
} finally {
  server.close()
}
console.log(JSON.stringify(results))
