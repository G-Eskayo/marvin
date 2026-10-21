// Evidence capture for marvin#555 (GitHub checks progress on MR Review cards): drives the built app against a sandbox
// HOME whose ~/.agents/bin/gh is a fake that serves PR lists from $HOME/fixture/prs-<owner>_<repo>.json, never the real
// store or GitHub. Writes that fixture itself, with check times relative to now, so the live clock shows real values.
// Usage: HOME=<sandbox> node check_progress_evidence.mjs <out-dir> <scenario: running|passed>
import { chromium } from 'playwright-core'
import { spawn } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'
import { captureLaunchEnv } from '../src/lib/screenshot_capture.js'
import { freePort } from '../src/lib/cdp_capture.js'

const APP = path.resolve(import.meta.dirname, '..')
const [OUT, SCENARIO = 'running'] = process.argv.slice(2)
const HOME = process.env.HOME
if (!OUT || !fs.existsSync(path.join(HOME, '.agents', 'bin', 'gh')) || HOME === '/Users/gileskayo') {
  console.error('usage: HOME=<sandbox with a fake ~/.agents/bin/gh> node check_progress_evidence.mjs <out-dir> <running|passed>')
  process.exit(1)
}
const iso = (secondsAgo) => new Date(Date.now() - secondsAgo * 1000).toISOString().replace(/\.\d+Z$/, 'Z')
const run = (name, started, finished) => ({
  __typename: 'CheckRun', name, workflowName: 'CI',
  status: finished == null ? 'IN_PROGRESS' : 'COMPLETED', conclusion: finished == null ? '' : 'SUCCESS',
  startedAt: iso(started), completedAt: finished == null ? null : iso(finished),
  detailsUrl: 'https://github.com/G-Eskayo/clarity-captions/actions'
})
// Gil's example (2026-10-21): two finished, the iOS build still running about four minutes in.
const rollup = SCENARIO === 'passed'
  ? [run('Website checks (site/)', 600, 552), run('CaptionCore unit tests', 599, 407), run('App builds (iOS Simulator)', 600, 300)]
  : [run('Website checks (site/)', 245, 197), run('CaptionCore unit tests', 244, 52), run('App builds (iOS Simulator)', 245, null)]
const prs = [{
  number: 148, title: 'Captions keep the last line on screen while the speaker pauses',
  url: 'https://github.com/G-Eskayo/clarity-captions/pull/148', body: 'Closes G-Eskayo/clarity-captions#147\n\nKeeps the last caption line visible during pauses.',
  files: [{ path: 'Packages/CaptionCore/Sources/CaptionCore/LineHold.swift' }], baseRefName: 'main', headRefName: 'ticket/147-line-hold',
  headRefOid: '0000000000000000000000000000000000000148', mergeable: 'MERGEABLE', statusCheckRollup: rollup
}]
fs.mkdirSync(path.join(HOME, 'fixture'), { recursive: true })
fs.writeFileSync(path.join(HOME, 'fixture', 'prs-G-Eskayo_clarity-captions.json'), JSON.stringify(prs))
fs.mkdirSync(OUT, { recursive: true })

const bin = path.join(APP, 'node_modules/electron/dist/Electron.app/Contents/MacOS/Electron')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const port = await freePort()
const proc = spawn(bin, [APP, '--no-sandbox', `--remote-debugging-port=${port}`], { env: captureLaunchEnv(process.env), stdio: 'ignore' })
let b
for (let i = 0; i < 120 && !b; i++) { try { b = await chromium.connectOverCDP(`http://127.0.0.1:${port}`) } catch { await sleep(250) } }
let page
for (let i = 0; i < 40 && !page; i++) { page = b.contexts()[0]?.pages().find((p) => p.url() && !p.url().startsWith('devtools')); if (!page) await sleep(250) }
await page.setViewportSize({ width: 1280, height: 640 })
await sleep(9000)
const click = (sel, text) => page.evaluate(([s, t]) => {
  const el = [...document.querySelectorAll(s)].find((e) => !t || e.textContent.trim().startsWith(t))
  if (!el) throw new Error(`no ${s} ${t || ''}`)
  el.click()
}, [sel, text])
const shot = async (name) => { await sleep(1200); await page.screenshot({ path: `${OUT}/pr-555-${name}.png` }); console.log('shot', name) }
try {
  await click('button', 'MR Review')
  await sleep(4000)
  if (SCENARIO === 'passed') {
    await shot('all-passed')
  } else {
    await shot('running-collapsed')
    await click('[data-check-progress] button')
    await shot('running-expanded')
  }
} finally {
  await b.close()
  proc.kill('SIGTERM')
}
