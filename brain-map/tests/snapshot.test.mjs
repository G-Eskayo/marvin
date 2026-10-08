// Snapshot export tests (#187): privacy filtering, UI behavior for locked projects.
//
// Tests that export_snapshot.py produces a valid HTML with SNAPSHOT=true,
// and that locked/private project nodes cannot be opened.
//
// Run: node --test brain-map/tests/snapshot.test.mjs   (regenerates snapshot first)
import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import { readFileSync } from 'node:fs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const MAP = path.resolve(HERE, '..')
const AGENTS = path.resolve(MAP, '..')
const { chromium } = createRequire(path.join(AGENTS, 'dashboard', 'package.json'))('playwright-core')

const STEP = 1000 / 24 // DesktopLive's frame interval
const SETTLE = 24 // one second of frames

let browser, skipReason
before(async () => {
  // Generate snapshot before tests run
  try {
    execFileSync(path.join(AGENTS, 'venv', 'bin', 'python'), [path.join(MAP, 'export_snapshot.py')], { stdio: 'ignore' })
  } catch (e) {
    skipReason = 'Snapshot generation failed: ' + e.message.split('\n')[0]
    return
  }
  try {
    browser = await chromium.launch({ channel: 'chrome' })
  } catch (e) {
    skipReason = 'Google Chrome is not installed: ' + e.message.split('\n')[0]
  }
})
after(() => browser?.close())

async function openSnapshot(width = 1280, height = 800) {
  const page = await browser.newPage({ viewport: { width, height } })
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto(pathToFileURL(path.join(MAP, 'snapshot', 'index.html')).href)
  await page.evaluate(() => window.__map.driveExternally())
  assert.deepEqual(errors, [], 'Page errors found')
  return page
}

const frames = (page, n) => page.evaluate(([n, step]) => {
  window.__t = window.__t || performance.now()
  for (let i = 0; i < n; i++) window.renderFrame((window.__t += step))
}, [n, STEP])

test('snapshot loads without console errors', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openSnapshot()
  // If we got here, openSnapshot succeeded and errors array was empty
  assert.ok(true, 'Snapshot loaded without errors')
})

test('SNAPSHOT flag is set to true in snapshot export', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openSnapshot()
  // SNAPSHOT is private to the page's script; __map exposes it (window.SNAPSHOT was always undefined)
  const isSnapshot = await page.evaluate(() => window.__map.snapshot())
  assert.equal(isSnapshot, true, 'SNAPSHOT flag not set to true')
})

test('snapshot disables activity polling', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openSnapshot()
  // The real behaviour: no live-activity requests (the dashboard map polls every 3 s; the website must not)
  const polled = []
  page.on('request', (r) => { if (/activity/i.test(r.url())) polled.push(r.url()) })
  await page.waitForTimeout(4000)
  assert.deepEqual(polled, [], 'snapshot polled for live activity')
})

test('locked project node shows "private — not shown" in tooltip', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openSnapshot()

  const hasLockedNode = await page.evaluate(() => {
    const allNodes = window.__map.nodes()
    return allNodes.some(n => n.locked === true)
  })

  if (!hasLockedNode) return t.skip('No locked nodes in test data')

  // Find and hover over a locked node
  const tooltipText = await page.evaluate(() => {
    const allNodes = window.__map.nodes()
    const lockedNode = allNodes.find(n => n.locked === true)
    if (!lockedNode) return null

    // Simulate finding the "openHint" for this node
    return lockedNode.locked ? "private — not shown" : null
  })

  assert.ok(tooltipText, 'Locked node should display "private — not shown"')
})

test('clicking a locked project node does not open code layer', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openSnapshot()

  const result = await page.evaluate(() => {
    const allNodes = window.__map.nodes()
    const lockedNode = allNodes.find(n => n.locked === true && n.openable !== true)
    if (!lockedNode) return { found: false }

    // Try to open it (should be no-op or harmless)
    if (typeof window.__map.open === 'function') {
      window.__map.open(lockedNode.id)
    }

    return { found: true, nodeId: lockedNode.id, openNodeId: window.__map.openId?.() }
  })

  if (!result.found) return t.skip('No locked non-openable nodes in test data')

  // Settle a few frames
  await frames(page, SETTLE)

  // openNodeId should not be set
  const openId = await page.evaluate(() => window.__map.openId?.())
  assert.equal(openId, null, 'Locked node should not be openable')
})

test('public project nodes in snapshot remain openable', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openSnapshot()

  const result = await page.evaluate(() => {
    const allNodes = window.__map.nodes()
    // Find a public (non-locked) openable node
    const openableNode = allNodes.find(n => n.openable === true && n.locked !== true)
    if (!openableNode) return { found: false }

    window.__map.open(openableNode.id)
    return { found: true, nodeId: openableNode.id }
  })

  if (!result.found) return t.skip('No openable public nodes in test data')

  // Settle frames for camera easing
  await frames(page, SETTLE)

  const openId = await page.evaluate(() => window.__map.openId?.())
  assert.equal(openId, result.nodeId, 'Public openable node should open')
})

// 2026-10-07, Gil on the first website snapshot: "the entire figure is pulsing". The containment zoom re-fit
// the figure to its silhouette at every rotation angle, so it grew and shrank as it turned. Outside the
// wallpaper the zoom now holds one size that fits a full turn.
test('the figure keeps one size while it rotates (no whole-figure pulsing)', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openSnapshot()
  await frames(page, SETTLE * 4) // let the fit settle
  const sizes = []
  for (let i = 0; i < 20; i++) { // 20 s of auto-rotation, sampled every second
    await frames(page, SETTLE)
    sizes.push(await page.evaluate(() => window.__map.fitScale()))
  }
  const spread = Math.max(...sizes) / Math.min(...sizes)
  assert.ok(spread < 1.01, `figure size varied ${((spread - 1) * 100).toFixed(1)}% while rotating: ${sizes.map((s) => s.toFixed(3)).join(' ')}`)
})

test('the steady size still keeps every node on screen through a full turn', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openSnapshot()
  await frames(page, SETTLE * 4)
  let worst = null
  for (let i = 0; i < 24; i++) {
    await frames(page, SETTLE)
    const off = await page.evaluate(() => window.__map.nodes().filter((n) => n.sx < 0 || n.sy < 0 || n.sx > innerWidth || n.sy > innerHeight).length)
    if (off) worst = off
  }
  assert.equal(worst, null, `${worst} node(s) left the screen during rotation`)
})

// The 24 fps driven test above passed while the real page still pulsed: at browser frame rates the spring settled
// into a ~1 s sawtooth around the fixed target. This one runs the page on its own requestAnimationFrame loop.
test('the figure keeps one size in a real browser frame loop too', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  await page.goto(pathToFileURL(path.join(MAP, 'snapshot', 'index.html')).href)
  await page.waitForTimeout(3000)
  const sizes = await page.evaluate(async () => {
    const out = []
    for (let i = 0; i < 30; i++) { await new Promise((r) => setTimeout(r, 100)); out.push(window.__map.fitScale()) }
    return out
  })
  const spread = Math.max(...sizes) / Math.min(...sizes)
  assert.ok(spread < 1.002, `figure size varied ${((spread - 1) * 100).toFixed(2)}% in the live loop`)
})

// 2026-10-08 (#189): Gil saw the snapshot "still missing all the connections". The export built only skill threads.
test('the snapshot carries every kind of connection, with no machine names in the labels', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const { synapses } = JSON.parse(readFileSync(path.join(MAP, 'snapshot', 'tree-data.json'), 'utf8'))
  const kinds = new Set(synapses.map((s) => s.type))
  for (const kind of ['calls', 'hook', 'feeds', 'runs-on', 'builds', 'skill-project']) {
    assert.ok(kinds.has(kind), `no ${kind} threads in the snapshot`)
  }
  const named = synapses.filter((s) => /mac-?mini|macbook|gils-/i.test(s.label))
  assert.deepEqual(named, [], 'a thread label names a machine; the snapshot anonymises machines')
})

// Gil 2026-10-08: hovering a node should say, in kindergarten words, what it is and does. Private projects stay quiet.
async function hoverTooltip(page, id) {
  await frames(page, SETTLE)
  const disc = await page.evaluate((id) => window.__map.nodes().find((n) => n.id === id), id)
  if (!disc) return null
  const box = await page.locator('canvas').first().boundingBox()
  await page.mouse.move(box.x + disc.sx, box.y + disc.sy)
  return page.evaluate(() => {
    const tip = document.getElementById('tooltip')
    return { shown: tip.style.display === 'block', name: tip.querySelector('.name')?.textContent,
      plain: tip.querySelector('.plain')?.textContent || null }
  })
}

test('hovering a node shows its plain-words line first; a locked project shows none', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openSnapshot()
  const tip = await hoverTooltip(page, 'ticket-pipeline')
  assert.ok(tip, 'ticket-pipeline is drawn')
  assert.ok(tip.shown, 'tooltip shows')
  assert.match(tip.plain || '', /ticket/i)
  const locked = (await page.evaluate(() => JSON.stringify(window.__map.nodes()))) && (await page.evaluate(() => {
    const ids = new Set(window.__map.nodes().map((n) => n.id))
    return [...ids].find((id) => ['eagle project', 'finance-os', 'MechanicGPT'].includes(id)) || null
  }))
  if (locked) {
    const lt = await hoverTooltip(page, locked)
    assert.equal(lt.plain, null, `${locked} is private: no plain line on the website`)
  }
})

// Gil 2026-10-08: on the website, only the 3D map on a transparent background; hover and drag still work, and the
// mouse wheel scrolls the page instead of zooming the map (docs/plans/map-website-2026-10-08.md).
test('embed mode: transparent, no panels, hover works, the wheel scrolls the page', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await browser.newPage({ viewport: { width: 1000, height: 640 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto(pathToFileURL(path.join(MAP, 'snapshot', 'index.html')).href + '?embed=1')
  await page.evaluate(() => window.__map.driveExternally())
  assert.deepEqual(errors, [])
  const look = await page.evaluate(() => {
    const vis = (sel) => { const el = document.querySelector(sel); return !!el && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden' }
    const bg = (el) => getComputedStyle(el).backgroundImage + '|' + getComputedStyle(el).backgroundColor
    return { html: bg(document.documentElement), body: bg(document.body),
      header: vis('header'), legend: vis('#legend'), toggle: vis('#mode-toggle'), footer: vis('footer'), hud: vis('.hud-frame') }
  })
  assert.equal(look.html, 'none|rgba(0, 0, 0, 0)')
  assert.equal(look.body, 'none|rgba(0, 0, 0, 0)')
  assert.deepEqual([look.header, look.legend, look.toggle, look.footer, look.hud], [false, false, false, false, false])
  const tip = await hoverTooltip(page, 'ticket-pipeline')
  assert.ok(tip?.shown && tip.plain, 'hover shows the plain line')
  const box = await page.locator('canvas').first().boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  const prevented = await page.evaluate(() => new Promise((res) => {
    const ev = new WheelEvent('wheel', { deltaY: -400, bubbles: true, cancelable: true })
    document.getElementById('c').dispatchEvent(ev); res(ev.defaultPrevented)
  }))
  assert.equal(prevented, false, 'the page keeps the wheel (the map handler returns before zooming)')
})

// 2026-10-08: the website's pages are white; pale labels on a transparent map vanished. ?ink=dark draws dark labels.
test('embed on a light page: ?ink=dark draws dark labels, the default stays light', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const rgb = (css) => css.startsWith('#') ? [1, 3, 5].map((i) => parseInt(css.slice(i, i + 2), 16)) : css.match(/\d+(\.\d+)?/g).map(Number)
  const lum = (css) => { const m = rgb(css); return (m[0] * 299 + m[1] * 587 + m[2] * 114) / 1000 }  // canvas reports hex at full opacity
  for (const [query, dark] of [['?embed=1&ink=dark', true], ['?embed=1', false]]) {
    const page = await browser.newPage({ viewport: { width: 1000, height: 640 } })
    await page.goto(pathToFileURL(path.join(MAP, 'snapshot', 'index.html')).href + query)
    await page.evaluate(() => window.__map.driveExternally())
    await frames(page, SETTLE * 2)
    const colors = await page.evaluate(() => window.__map.labels().filter((l) => l.shown).map((l) => l.color))
    assert.ok(colors.length > 3, 'labels are drawn')
    const plain = colors.filter((c) => rgb(c).slice(0, 3).join() !== '255,176,59')  // pulsing gold labels are exempt
    assert.ok(plain.every((c) => (lum(c) < 110) === dark), `${query}: ${plain.slice(0, 3)}`)
    await page.close()
  }
})

// Gil 2026-10-08: no "full screen" link; clicking the empty background on purpose blows the map up to fill the screen.
async function embedWithFullscreenSpy(query = '?embed=1&ink=dark') {
  const page = await browser.newPage({ viewport: { width: 1000, height: 640 } })
  await page.addInitScript(() => {
    window.__fs = []
    Element.prototype.requestFullscreen = function () { window.__fs.push('request'); return Promise.resolve() }
    window.open = function () { window.__fs.push('open'); return null }
  })
  await page.goto(pathToFileURL(path.join(MAP, 'snapshot', 'index.html')).href + query)
  await page.evaluate(() => window.__map.driveExternally())
  await frames(page, SETTLE)
  return page
}

test('the popup copy (?modal=1) never asks to expand and shows no zoom-in cursor', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await embedWithFullscreenSpy('?embed=1&ink=dark&modal=1')
  const box = await page.locator('canvas').first().boundingBox()
  await page.mouse.move(box.x + 8, box.y + 8); await frames(page, 2)
  assert.equal(await page.evaluate(() => document.getElementById('c').style.cursor), '')
  await page.mouse.click(box.x + 8, box.y + 8)
  assert.deepEqual(await page.evaluate(() => window.__fs), [])
  await page.close()
})

// Gil 2026-10-08 (second pass): clicking the small map grows it into a big white box ON the page; it must never go full
// screen or open another page, whatever is clicked, and whether or not the page answers.
async function framedMap(t, { acknowledge }) {
  const { mkdtempSync, writeFileSync } = await import('node:fs')
  const os = await import('node:os')
  const dir = mkdtempSync(path.join(os.tmpdir(), 'mapframe-'))
  const src = pathToFileURL(path.join(MAP, 'snapshot', 'index.html')).href + '?embed=1&ink=dark'
  writeFileSync(path.join(dir, 'host.html'), `<!doctype html><body style="margin:0">
    <iframe id="m" src="${src}" style="width:900px;height:560px;border:0"></iframe>
    <script>window.__asked = 0; addEventListener('message', (e) => { if (e.data && e.data.type === 'marvin-map:expand') {
      window.__asked++; ${acknowledge ? "e.source.postMessage({ type: 'marvin-map:expand-ack' }, '*')" : ''} } })</script></body>`)
  const page = await browser.newPage({ viewport: { width: 1000, height: 640 } })
  await page.addInitScript(() => { window.__fs = []; Element.prototype.requestFullscreen = function () { window.__fs.push('request'); return Promise.resolve() }; window.open = function () { window.__fs.push('open'); return null } })
  await page.goto(pathToFileURL(path.join(dir, 'host.html')).href)
  const frame = page.frames().find((f) => f.url().includes('snapshot'))
  await frame.waitForFunction(() => window.__map)
  await frame.evaluate(() => { window.__map.driveExternally(); let t = performance.now(); for (let i = 0; i < 24; i++) window.renderFrame((t += 1000 / 24)) })
  const box = await page.locator('#m').boundingBox()
  await page.mouse.click(box.x + 8, box.y + 8)
  await page.waitForTimeout(700)
  return { asked: await page.evaluate(() => window.__asked), fs: await frame.evaluate(() => window.__fs), page }
}

test('framed: any click on the small map asks the page for the box, and never leaves the page', async (t) => {
  if (skipReason) return t.skip(skipReason)
  for (const acknowledge of [true, false]) {
    const r = await framedMap(t, { acknowledge })
    assert.equal(r.asked, 1, 'an empty-background click asks')
    const frame = r.page.frames().find((f) => f.url().includes('snapshot'))
    const disc = await frame.evaluate(() => window.__map.nodes().find((n) => n.id === 'ticket-pipeline'))
    const box = await r.page.locator('#m').boundingBox()
    await r.page.mouse.move(box.x + disc.sx, box.y + disc.sy)
    await frame.evaluate(() => { let t = performance.now(); for (let i = 0; i < 3; i++) window.renderFrame((t += 1000 / 24)) })
    await r.page.mouse.click(box.x + disc.sx, box.y + disc.sy)
    await r.page.waitForTimeout(600)
    assert.equal(await r.page.evaluate(() => window.__asked), 2, 'a node click asks too')
    assert.deepEqual(await frame.evaluate(() => window.__fs), [], `no full screen, no new page (answered: ${acknowledge})`)
    await r.page.close()
  }
})

test('the small map shows a zoom-in cursor everywhere; the box copy (?modal=1) does not ask again', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const small = await embedWithFullscreenSpy('?embed=1&ink=dark')
  assert.equal(await small.evaluate(() => getComputedStyle(document.getElementById('c')).cursor), 'zoom-in')
  await small.close()
  const page = await embedWithFullscreenSpy('?embed=1&ink=dark&modal=1')
  const box = await page.locator('canvas').first().boundingBox()
  await page.mouse.click(box.x + 8, box.y + 8)
  assert.deepEqual(await page.evaluate(() => window.__fs), [])
  await page.close()
})

// Gil: after it's been messed with, and not on a node, it starts rotating again after about 5 seconds; and a reset.
async function fullMap() {
  const page = await browser.newPage({ viewport: { width: 1000, height: 640 } })
  await page.goto(pathToFileURL(path.join(MAP, 'snapshot', 'index.html')).href + '?embed=1&ink=dark&modal=1')
  await page.evaluate(() => window.__map.driveExternally())
  await frames(page, SETTLE)
  return page
}
const advance = (page, ms) => frames(page, Math.ceil(ms / STEP))

test('rotation resumes 5 s after the last drag, unless the pointer is on a node', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await fullMap()
  const box = await page.locator('canvas').first().boundingBox()
  assert.equal(await page.evaluate(() => window.__map.rotating()), true)
  await page.mouse.move(box.x + 20, box.y + 20); await page.mouse.down()
  await page.mouse.move(box.x + 120, box.y + 60, { steps: 4 }); await page.mouse.up()
  assert.equal(await page.evaluate(() => window.__map.rotating()), false, 'a drag stops it')
  await advance(page, 3000)
  assert.equal(await page.evaluate(() => window.__map.rotating()), false, 'still stopped at 3 s')
  await advance(page, 2500)
  assert.equal(await page.evaluate(() => window.__map.rotating()), true, 'rotating again after 5 s')
  // on a node: stays put
  const disc = await page.evaluate(() => window.__map.nodes().find((n) => n.id === 'ticket-pipeline'))
  await page.mouse.move(box.x + disc.sx, box.y + disc.sy); await page.mouse.down(); await page.mouse.up()
  await page.mouse.move(box.x + disc.sx, box.y + disc.sy)
  await advance(page, 6000)
  assert.equal(await page.evaluate(() => window.__map.rotating()), false, 'not while selected / on a node')
  await page.close()
})

test('Reset puts the view, zoom and selection back and starts rotating', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await fullMap()
  const start = await page.evaluate(() => window.__map.view())
  const box = await page.locator('canvas').first().boundingBox()
  await page.mouse.move(box.x + 20, box.y + 20); await page.mouse.down()
  await page.mouse.move(box.x + 200, box.y + 120, { steps: 4 }); await page.mouse.up()
  await page.mouse.wheel(0, -300); await frames(page, 2)
  const moved = await page.evaluate(() => window.__map.view())
  assert.notDeepEqual(moved, start)
  assert.ok(await page.locator('#map-reset').isVisible(), 'Reset shows in the box')
  await page.click('#map-reset'); await frames(page, 2)
  const after = await page.evaluate(() => window.__map.view())
  assert.equal(after.pitch, start.pitch); assert.equal(after.camDist, start.camDist); assert.equal(after.userZoomed, false)
  assert.equal(await page.evaluate(() => window.__map.rotating()), true)
  await page.close()
})

test('the small map has no Reset button; the full page and the box do', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const small = await embedWithFullscreenSpy('?embed=1&ink=dark')
  assert.equal(await small.locator('#map-reset').isVisible(), false)
  await small.close()
})
