// Body and Work (#854, a mock-up for review behind ?layout=work and the legend's layout row).
//
// Body is today's branches regrouped by Vitals region; Work is one node per project holding its workers (chat
// helpers, pipeline builders, spawned agents, the jobs serving it) and the files they touch. Gil, 2026-10-30: a worker
// shows only while it runs and leaves the moment it finishes cleanly; one that died stays red until a retry passes or
// it is dismissed from the tray. Labels: regions and projects, plus what is lit or red. The wallpaper shows the same
// layout and data. Links between the halves light only from real traffic (#843's rule). The default layout must
// stay exactly as it was.
//
// The ticket's break-it list: a worker whose project can't be found (Unassigned, never dropped), a project with 30
// workers, and 50 helpers starting and stopping in a minute. (0 and 42 projects: brain-map/tests/test_work_layout.py.)
//
// Run: node --test brain-map/tests/work.test.mjs   (regenerates index.html first)
import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { readFileSync, writeFileSync, unlinkSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const MAP = path.resolve(HERE, '..')
const AGENTS = path.resolve(MAP, '..')
const { chromium } = createRequire(path.join(AGENTS, 'dashboard', 'package.json'))('playwright-core')

const STEP = 1000 / 24
const SECOND = 24

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

async function openMap({ work = true, init, file = 'index.html', query } = {}) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  if (init) await page.addInitScript(init)
  await page.goto(pathToFileURL(path.join(MAP, file)).href + (query ?? (work ? '?layout=work' : '')))
  if (!/wallpaper=1/.test(query || '')) await page.evaluate(() => window.__map.driveExternally())
  page.errors = errors
  return page
}

const frames = (page, n) => page.evaluate(([n, step]) => {
  window.__t = window.__t || performance.now()
  for (let i = 0; i < n; i++) window.renderFrame((window.__t += step))
}, [n, STEP])
const m = (page, fn, arg) => page.evaluate(fn, arg)
const apply = (page, doc) => page.evaluate((doc) => window.__map.applyWork(doc), doc)
const nowS = () => Date.now() / 1000
const helperW = (id, project, extra = {}) => ({ id: `helper:${id}`, name: `helper ${id}`, kind: 'helper', state: 'running',
  project, agent: id, ended: null, desc: 'Chat helper: running', ...extra })

// A real project from the generated Work half (the catalog's own), and one that has a skill to touch.
async function aProject(page) {
  const projects = await m(page, () => window.__map.workProjects())
  const p = projects.find((x) => x.projectId)
  assert.ok(p, 'no project in the generated Work half')
  return p
}

test('the default layout is exactly today\'s: same trunks, no halves, and a layout row to switch', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap({ work: false })
  const data = JSON.parse(readFileSync(path.join(MAP, 'tree-data.json'), 'utf8'))
  assert.equal(await m(page, () => window.__map.layout()), 'today')
  assert.deepEqual((await m(page, () => window.__map.rootChildren())).map((c) => c.id), data.tree.children.map((c) => c.id))
  assert.equal(await m(page, () => window.__map.has('half:work')), false)
  const rows = await m(page, () => window.__map.legendRows())
  assert.ok(rows.some((r) => r.startsWith('layout') && r.endsWith('today')), rows.join(' | '))
  assert.deepEqual(page.errors, [])
  await page.close()
})

test('?layout=work shows Body by the Vitals regions and Work with the catalog\'s projects and Unassigned', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  assert.equal(await m(page, () => window.__map.layout()), 'work')
  assert.deepEqual((await m(page, () => window.__map.rootChildren())).map((c) => c.name), ['Body', 'Work'])
  const regions = (await m(page, () => window.__map.childrenOf('half:body'))).map((c) => c.name)
  assert.deepEqual(regions, ['Pipeline', 'GitHub', 'Code & tests', 'Skills & tools', 'Code sync', 'Producers', 'Energy', 'Body'])
  const work = JSON.parse(readFileSync(path.join(MAP, 'work.json'), 'utf8'))
  const projects = (await m(page, () => window.__map.workProjects())).map((p) => p.projectId)
  assert.deepEqual(projects, work.projects.map((p) => p.id).concat([null]))
  await frames(page, 2)
  assert.deepEqual(page.errors, [])
  await page.close()
})

test('a helper that starts appears under its project on the next read of work.json, and lights', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  await frames(page, 1)
  await apply(page, { workers: [helperW('n1', p.projectId)] })
  await frames(page, 2)
  const w = (await m(page, () => window.__map.workers())).find((x) => x.id === 'helper:n1')
  assert.equal(w.parent, p.id)
  assert.ok(await m(page, () => window.__map.level('helper:n1')) > 0.3, 'a new worker does not light')
  await page.close()
})

test('the page reads work.json on its own activity tick: a new helper is on the map within seconds', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap({
    init: () => {
      const real = window.fetch.bind(window)
      window.fetch = (url, opts) => String(url).includes('work.json')
        ? Promise.resolve(new Response(JSON.stringify({ workers: [{ id: 'helper:poll1', name: 'polled', kind: 'helper', state: 'running', project: null }] })))
        : real(url, opts)
    }
  })
  const deadline = Date.now() + 5000
  let found = false
  while (!found && Date.now() < deadline) {
    await page.waitForTimeout(250)
    found = (await m(page, () => window.__map.workers())).some((w) => w.id === 'helper:poll1')
  }
  assert.ok(found, 'the polled worker never appeared')
  await page.close()
})

test('a worker whose project cannot be found is under Unassigned, never dropped', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await apply(page, { workers: [helperW('u1', null), helperW('u2', 'no-such-project'), { id: 'job:mystery', name: 'mystery', kind: 'job', state: 'idle', project: null }] })
  const ws = await m(page, () => window.__map.workers())
  for (const id of ['helper:u1', 'helper:u2', 'job:mystery']) assert.equal(ws.find((w) => w.id === id)?.parent, 'Unassigned', id)
  await page.close()
})

test('a worker that finishes cleanly leaves at once; one that died stays red until a retry passes', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  await apply(page, { workers: [helperW('ok1', p.projectId), helperW('d1', p.projectId, { state: 'failed', ended: 1000 })] })
  assert.equal(await m(page, () => window.__map.failed('helper:d1')), true)
  // ok1 finished: work.json stops listing it. d1 is still listed, red, however long ago it died.
  await apply(page, { workers: [helperW('d1', p.projectId, { state: 'failed', ended: 1000 })] })
  assert.equal(await m(page, () => window.__map.has('helper:ok1')), false)
  assert.equal(await m(page, () => window.__map.failed('helper:d1')), true)
  // the retry runs: no longer red
  await apply(page, { workers: [helperW('d1', p.projectId)] })
  assert.equal(await m(page, () => window.__map.failed('helper:d1')), false)
  // and passes: gone
  await apply(page, { workers: [] })
  assert.equal(await m(page, () => window.__map.has('helper:d1')), false)
  await page.close()
})

test('a job shows only while it runs or after it failed, and leaves once work.json drops it', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  const job = (id, state) => ({ id: `job:${id}`, name: id, kind: 'job', state, project: p.projectId, ended: state === 'failed' ? 5 : null })
  await apply(page, { workers: [job('runs', 'running'), job('broke', 'failed')] })
  assert.ok(await m(page, () => window.__map.has('job:runs')))
  assert.equal(await m(page, () => window.__map.failed('job:broke')), true)
  await apply(page, { workers: [job('broke', 'failed')] })
  assert.equal(await m(page, () => window.__map.has('job:runs')), false)
  await page.close()
})

test('a dead worker tapped in the tray is dismissed: gone, and stays gone for that failure only', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  const dead = (ended) => ({ workers: [helperW('z1', p.projectId, { state: 'failed', ended })] })
  await apply(page, dead(1000))
  await frames(page, 2)
  await m(page, () => window.__map.openTray())
  await page.click('[data-dismiss="helper:z1"]')
  assert.equal(await m(page, () => window.__map.has('helper:z1')), false)
  await apply(page, dead(1000)) // the same failure, read again
  assert.equal(await m(page, () => window.__map.has('helper:z1')), false)
  await apply(page, dead(2000)) // it was retried and died again: a new failure shows
  assert.equal(await m(page, () => window.__map.failed('helper:z1')), true)
  assert.equal(await m(page, () => window.__map.dismiss('half:body')), false, 'only a red worker can be dismissed')
  await page.close()
})

test('a dismissal outlives a reload in the same browser', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } })
  const page = await ctx.newPage()
  await page.goto(pathToFileURL(path.join(MAP, 'index.html')).href + '?layout=work')
  const doc = { workers: [helperW('r1', null, { state: 'failed', ended: 7 })] }
  await page.evaluate((d) => window.__map.applyWork(d), doc)
  assert.equal(await page.evaluate(() => window.__map.dismiss('helper:r1')), true)
  await page.reload()
  await page.evaluate((d) => window.__map.applyWork(d), doc)
  assert.equal(await page.evaluate(() => window.__map.has('helper:r1')), false)
  await ctx.close()
})

test('a project with 30 workers shows all 30 and still draws', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  const workers = Array.from({ length: 30 }, (_, i) => helperW(`t${i}`, p.projectId))
  await apply(page, { workers })
  await frames(page, 3 * SECOND)
  const under = (await m(page, () => window.__map.workers())).filter((w) => w.parent === p.id && w.id.startsWith('helper:t'))
  assert.equal(under.length, 30)
  assert.deepEqual(page.errors, [])
  await page.close()
})

test('worker churn: 50 helpers starting and stopping in a minute', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  const before = (await m(page, () => window.__map.workers())).length
  const live = new Map()
  for (let i = 0; i < 50; i++) {
    live.set(`c${i}`, helperW(`c${i}`, p.projectId))
    await apply(page, { workers: [...live.values()] })
    await frames(page, SECOND / 2)
    if (i >= 5) { live.delete(`c${i - 5}`); await apply(page, { workers: [...live.values()] }) }
    await frames(page, SECOND / 2)
  }
  const ws = (await m(page, () => window.__map.workers())).filter((w) => w.id.startsWith('helper:c'))
  assert.deepEqual(ws.map((w) => w.id).sort(), [...live.keys()].map((k) => `helper:${k}`).sort())
  await apply(page, { workers: [] })
  await frames(page, SECOND)
  assert.equal((await m(page, () => window.__map.workers())).filter((w) => w.kind !== 'job').length, 0)
  assert.ok((await m(page, () => window.__map.workers())).length <= before)
  assert.deepEqual(page.errors, [])
  await page.close()
})

test('a helper\'s own file touch: the worker lights, the file is a leaf under it, the link to the body part lights', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  await apply(page, { workers: [helperW('x1', p.projectId)] })
  await frames(page, 60 * SECOND) // let the start light fade
  const owner = await m(page, () => window.__map.codeOwnerWithFile())
  assert.ok(owner, 'no node on the map owns a source file')
  await m(page, (f) => window.triggerActivity({ skill: 'MARVIN', tool: 'Read', ts: 1.8e9, agent: 'x1', file: f }), owner.file)
  await frames(page, 2)
  const leafId = `file:x1:${owner.file}`
  assert.ok(await m(page, (id) => window.__map.has(id), leafId), 'no file leaf under the worker')
  assert.equal((await m(page, (id) => window.__map.parentOf(id), leafId)), 'helper:x1')
  assert.ok(await m(page, () => window.__map.level('helper:x1')) > 0.3, 'the worker did not light')
  const links = await m(page, () => window.__map.links())
  assert.ok(links.some((l) => l.type === 'touches' && l.a === 'helper:x1' && l.level > 0), JSON.stringify(links))
  await page.close()
})

test('a helper event with no file lights the worker but no link', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  await apply(page, { workers: [helperW('y1', p.projectId)] })
  await frames(page, 60 * SECOND)
  await m(page, () => window.triggerActivity({ skill: 'MARVIN', tool: 'Bash', ts: 1.8e9, agent: 'y1' }))
  await frames(page, 2)
  assert.ok(await m(page, () => window.__map.level('helper:y1')) > 0.3)
  assert.deepEqual((await m(page, () => window.__map.links())).filter((l) => l.a === 'helper:y1'), [])
  await page.close()
})

test('an event naming a helper that is not on the map draws nothing new', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const before = await m(page, () => window.__map.workers())
  await m(page, () => window.triggerActivity({ skill: 'MARVIN', tool: 'Read', ts: 1.8e9, agent: 'ghost', file: 'lib/x.py' }))
  await frames(page, 2)
  assert.deepEqual(await m(page, () => window.__map.workers()), before)
  assert.equal(await m(page, () => window.__map.has('file:ghost:lib/x.py')), false)
  await page.close()
})

test('a work.json worker can never take over a body part\'s id', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await apply(page, { workers: [{ id: 'half:body', name: 'evil', kind: 'helper', state: 'failed', project: null }] })
  assert.deepEqual((await m(page, () => window.__map.rootChildren())).map((c) => c.name), ['Body', 'Work'])
  assert.equal(await m(page, () => window.__map.failed('half:body')), false)
  await page.close()
})

test('in the work layout, with nothing happening, nothing moves (running workers do not pulse on their own)', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  await apply(page, { workers: [helperW('s1', p.projectId)] })
  await page.waitForTimeout(700) // grow-in and shrink-out run on the real clock (BIRTH_MS, DEATH_MS)
  await frames(page, 60 * SECOND)
  const a = await m(page, () => document.getElementById('c').toDataURL())
  await apply(page, { workers: [helperW('s1', p.projectId)] }) // the same state read again changes nothing
  await frames(page, 3 * SECOND)
  const b = await m(page, () => document.getElementById('c').toDataURL())
  assert.ok(a === b, 'the canvas changed with nothing happening')
  await page.close()
})

test('the legend\'s layout row switches between the two layouts', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap({ work: false })
  await Promise.all([page.waitForNavigation(), page.click('#layout-toggle')])
  assert.match(page.url(), /[?&]layout=work\b/)
  assert.equal(await m(page, () => window.__map.layout()), 'work')
  await Promise.all([page.waitForNavigation(), page.click('#layout-toggle')])
  assert.doesNotMatch(page.url(), /layout=work/)
  await page.close()
})

test('labels: with 300 nodes and 3 active, only regions, projects and the 3 are labelled; others on hover', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  await apply(page, { workers: [] }) // nothing red
  const count = await m(page, () => window.__map.nodeCount())
  const filler = Array.from({ length: Math.max(0, 300 - count) }, (_, i) => helperW(`l${i}`, p.projectId))
  await apply(page, { workers: filler })
  await page.waitForTimeout(700) // grow-in runs on the real clock
  await frames(page, 60 * SECOND) // the new workers' start light has gone
  assert.ok(await m(page, () => window.__map.nodeCount()) >= 300)
  const fixed = (await m(page, () => window.__map.childrenOf('half:body'))).length + (await m(page, () => window.__map.workProjects())).length
  for (const a of ['l1', 'l2', 'l3']) await m(page, (a) => window.triggerActivity({ skill: 'MARVIN', tool: 'Bash', ts: 1.8e9, agent: a }), a)
  await frames(page, SECOND)
  const shown = (await m(page, () => window.__map.labels())).filter((l) => l.alpha > 0)
  assert.ok(shown.length <= fixed + 3, `${shown.length} labels drawn, limit ${fixed} + 3`)
  assert.ok(!shown.some((l) => l.text === 'helper l10'), 'an idle worker is labelled')
  const pos = (await m(page, () => window.__map.nodes())).find((n) => n.id === 'helper:l10')
  await page.mouse.move(pos.sx, pos.sy)
  await frames(page, SECOND)
  const under = await m(page, () => window.__map.hovered()) // the nearest part under the pointer
  assert.ok(under && under.startsWith('helper:l'), `hovering picked ${under}`)
  const name = 'helper ' + under.slice(7)
  assert.ok((await m(page, () => window.__map.labels())).some((l) => l.text === name && l.alpha > 0), 'no label on hover')
  await page.close()
})

test('everything in Work wears the Work hue and each region has its own', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  await apply(page, { workers: [helperW('h1', p.projectId)] })
  assert.ok((await m(page, () => window.__map.workers())).every((w) => w.cat === 'work'))
  assert.equal(new Set((await m(page, () => window.__map.childrenOf('half:body'))).map((c) => c.cat)).size, 8)
  await page.close()
})

// ── parity: the wallpaper shows the same layout and data ──

test('the one layout setting drives the wallpaper too, and the hosts\' pushes keep it current', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const html = readFileSync(path.join(MAP, 'index.html'), 'utf8').replace('var DEFAULT_LAYOUT = "today";', 'var DEFAULT_LAYOUT = "work";')
  assert.match(html, /var DEFAULT_LAYOUT = "work";/)
  const file = 'index.layout-test.html'
  writeFileSync(path.join(MAP, file), html)
  try {
    const page = await openMap({ file, query: '?wallpaper=1' })
    assert.equal(await m(page, () => window.__map.layout()), 'work')
    await m(page, (doc) => window.applyWork(doc), { workers: [helperW('w1', null)] })
    assert.ok(await m(page, () => window.__map.has('helper:w1')))
    const data = JSON.parse(readFileSync(path.join(MAP, 'tree-data.json'), 'utf8'))
    await m(page, (d) => window.updateTreeData(d.tree, d.synapses, d.work), data)
    assert.deepEqual((await m(page, () => window.__map.rootChildren())).map((c) => c.name), ['Body', 'Work'])
    await m(page, (d) => window.updateTreeData(d.tree, d.synapses), data) // an older host: keep the Work layout
    assert.deepEqual((await m(page, () => window.__map.rootChildren())).map((c) => c.name), ['Body', 'Work'])
    assert.deepEqual(page.errors, [])
    await page.close()
    const today = await openMap({ file, query: '?layout=today' })
    assert.equal(await m(today, () => window.__map.layout()), 'today')
    await today.close()
  } finally {
    unlinkSync(path.join(MAP, file))
  }
})

// ── shape is a second cue for every kind of part (Gil, 2026-10-30, proposed for review) ──

test('each kind of part has its own shape: regions circles, projects diamonds, workers by kind, files dots', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const p = await aProject(page)
  await apply(page, { workers: [helperW('s-h', p.projectId), helperW('s-a', p.projectId, { kind: 'agent' }),
    { id: 'builder:o/r#1', name: '#1', kind: 'builder', state: 'running', project: p.projectId },
    { id: 'job:s-j', name: 's-j', kind: 'job', state: 'running', project: p.projectId }] })
  const owner = await m(page, () => window.__map.codeOwnerWithFile())
  await m(page, (f) => window.triggerActivity({ skill: 'MARVIN', tool: 'Read', ts: 1.8e9, agent: 's-h', file: f }), owner.file)
  await page.waitForTimeout(700)
  await frames(page, 2)
  const shape = (id) => m(page, (id) => window.__map.shapeOf(id), id)
  assert.equal(await shape('region:Pipeline'), 'circle')
  assert.equal(await shape(owner.node), 'circle')
  assert.equal(await shape(p.id), 'diamond')
  assert.equal(await shape('Unassigned'), 'diamond')
  assert.equal(await shape('helper:s-h'), 'triangle')
  assert.equal(await shape('helper:s-a'), 'triangle-dot')
  assert.equal(await shape('builder:o/r#1'), 'square')
  assert.equal(await shape('job:s-j'), 'hexagon')
  assert.equal(await shape(`file:s-h:${owner.file}`), 'dot')
  // the shape is what gets drawn: each one's drawn record carries it
  const drawn = Object.fromEntries((await m(page, () => window.__map.nodes())).map((n) => [n.id, n.shape]))
  assert.equal(drawn['builder:o/r#1'], 'square')
  assert.equal(await m(page, () => window.__map.layout()), 'work')
  await page.close()
})

test('shapes stay readable at 860 px: no project or worker is drawn smaller than 4 px', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await browser.newPage({ viewport: { width: 860, height: 900 } })
  await page.goto(pathToFileURL(path.join(MAP, 'index.html')).href + '?layout=work')
  await page.evaluate(() => window.__map.driveExternally())
  const p = (await page.evaluate(() => window.__map.workProjects())).find((x) => x.projectId)
  await page.evaluate((d) => window.__map.applyWork(d), { workers: Array.from({ length: 12 }, (_, i) => ({ id: `helper:sz${i}`, name: 'x', kind: ['helper', 'agent', 'builder', 'job'][i % 4], state: 'running', project: p.projectId })) })
  await page.waitForTimeout(700)
  await frames(page, 2 * SECOND)
  const small = (await page.evaluate(() => window.__map.nodes())).filter((n) => n.shape !== 'circle' && n.shape !== 'dot' && n.r < 4)
  assert.deepEqual(small, [])
  await page.close()
})

test('the default layout draws every node as a circle, as before', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap({ work: false })
  await frames(page, 2)
  assert.ok((await m(page, () => window.__map.nodes())).every((n) => n.shape === undefined || n.shape === 'circle'))
  await page.close()
})
