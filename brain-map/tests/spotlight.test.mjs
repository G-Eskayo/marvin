// Spotlight (marvin#873): the Vitals tab points at a row and the map lights that part and dims the rest. The page
// hosting the map sends {type: "marvin-map:spotlight", id}; the map selects that part (the same selection a click
// makes, which dims everything not connected to it) and answers {type: "marvin-map:spotlight-ack", id, found}, so the
// host can say "not on the map" for a part it doesn't have. null clears it. Nothing else about the map changes.
//
// Break-it: an id the map doesn't have, junk messages, a flood of hovers, and a message before the map is ready.
//
// Run: node --test brain-map/tests/spotlight.test.mjs   (regenerates index.html first)
import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const MAP = path.resolve(HERE, '..')
const AGENTS = path.resolve(MAP, '..')
const { chromium } = createRequire(path.join(AGENTS, 'dashboard', 'package.json'))('playwright-core')

let browser, skipReason
before(async () => {
  execFileSync(path.join(AGENTS, 'venv', 'bin', 'python'), [path.join(MAP, 'generate.py')], { stdio: 'ignore' })
  try {
    browser = await chromium.launch({ channel: 'chrome' })
  } catch (e) {
    skipReason = 'Google Chrome is not installed: ' + e.message.split('\n')[0]
  }
})
after(() => browser?.close())

async function openMap(query = '?layout=work') {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  page.errors = []
  page.on('pageerror', (e) => page.errors.push(e.message))
  // Collect the acks the map sends back to whoever asked (here the page itself).
  await page.addInitScript(() => {
    window.__acks = []
    window.addEventListener('message', (ev) => { if (ev.data && ev.data.type === 'marvin-map:spotlight-ack') window.__acks.push(ev.data) })
  })
  await page.goto(pathToFileURL(path.join(MAP, 'index.html')).href + query)
  await page.evaluate(() => window.__map.driveExternally())
  return page
}

const spot = (page, data) => page.evaluate((d) => new Promise((resolve) => {
  const n = window.__acks.length
  window.postMessage(d, '*')
  setTimeout(() => resolve(window.__acks.slice(n)), 50)
}), data)

test('a part the map has is selected (lit, the rest dimmed) and acknowledged as found', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const acks = await spot(page, { type: 'marvin-map:spotlight', id: 'region:Body' })
  assert.deepEqual(acks, [{ type: 'marvin-map:spotlight-ack', id: 'region:Body', found: true }])
  assert.equal(await page.evaluate(() => window.__map.selected()), 'region:Body')
  assert.deepEqual(page.errors, [])
})

test('a part the map does not have: found false, and nothing stays lit from before', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await spot(page, { type: 'marvin-map:spotlight', id: 'region:Pipeline' })
  const acks = await spot(page, { type: 'marvin-map:spotlight', id: 'errors@mac-mini-1' })
  assert.deepEqual(acks, [{ type: 'marvin-map:spotlight-ack', id: 'errors@mac-mini-1', found: false }])
  assert.equal(await page.evaluate(() => window.__map.selected()), null)
})

test('null clears the spotlight', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await spot(page, { type: 'marvin-map:spotlight', id: 'region:Body' })
  const acks = await spot(page, { type: 'marvin-map:spotlight', id: null })
  assert.deepEqual(acks, [{ type: 'marvin-map:spotlight-ack', id: null, found: false }])
  assert.equal(await page.evaluate(() => window.__map.selected()), null)
})

test('junk is ignored without an error or an answer', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await spot(page, { type: 'marvin-map:spotlight', id: 'region:Body' })
  for (const junk of ['marvin-map:spotlight', 42, null, { type: 'other', id: 'region:Pipeline' }, { type: 'marvin-map:spotlight', id: { evil: 1 } },
    { type: 'marvin-map:spotlight', id: 'x'.repeat(100_000) }, { type: 'marvin-map:spotlight', id: '__proto__' }, { type: 'marvin-map:spotlight', id: 'constructor' }]) {
    const acks = await spot(page, junk)
    if (junk && junk.type === 'marvin-map:spotlight' && typeof junk.id === 'string') assert.equal(acks[0].found, false)
    else assert.deepEqual(acks, [])
  }
  assert.equal(await page.evaluate(() => window.__map.selected()), null)
  assert.deepEqual(page.errors, [])
})

test('a flood of hovers ends on the last one', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await page.evaluate(() => {
    const ids = ['region:Body', 'region:Pipeline', 'region:GitHub', null, 'region:Producers']
    for (let i = 0; i < 500; i++) window.postMessage({ type: 'marvin-map:spotlight', id: ids[i % ids.length] }, '*')
  })
  await page.waitForTimeout(100)
  assert.equal(await page.evaluate(() => window.__map.selected()), 'region:Producers')
  assert.deepEqual(page.errors, [])
})

test("today's layout answers too (a region it lacks is simply not found)", async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap('')
  const acks = await spot(page, { type: 'marvin-map:spotlight', id: 'region:Body' })
  assert.equal(acks[0].found, false)
  const hit = await spot(page, { type: 'marvin-map:spotlight', id: 'MARVIN' })
  assert.equal(hit[0].found, true)
})

test('project:<id> finds that project\'s Work node by its project id (no names hard-coded in the host)', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = (await page.evaluate(() => window.__map.workProjects())).find((x) => x.projectId)
  assert.ok(p, 'no project with an id in the generated Work half')
  const acks = await spot(page, { type: 'marvin-map:spotlight', id: `project:${p.projectId}` })
  assert.deepEqual(acks, [{ type: 'marvin-map:spotlight-ack', id: `project:${p.projectId}`, found: true }])
  assert.equal(await page.evaluate(() => window.__map.selected()), p.id)
  const miss = await spot(page, { type: 'marvin-map:spotlight', id: 'project:no-such-project' })
  assert.equal(miss[0].found, false)
})
