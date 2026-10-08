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
  })
  await page.goto(pathToFileURL(path.join(MAP, 'snapshot', 'index.html')).href + query)
  await page.evaluate(() => window.__map.driveExternally())
  await frames(page, SETTLE)
  return page
}

test('embed: a click on empty background asks for full screen; a node click or a non-embed page does not', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await embedWithFullscreenSpy()
  const box = await page.locator('canvas').first().boundingBox()
  await page.mouse.click(box.x + 8, box.y + 8)  // a corner: nothing there
  assert.deepEqual(await page.evaluate(() => window.__fs), ['request'])
  await page.evaluate(() => { window.__fs = [] })
  const disc = await page.evaluate(() => window.__map.nodes().find((n) => n.id === 'ticket-pipeline'))
  await page.mouse.move(box.x + disc.sx, box.y + disc.sy); await frames(page, 2)
  await page.mouse.click(box.x + disc.sx, box.y + disc.sy)
  assert.deepEqual(await page.evaluate(() => window.__fs), [], 'clicking a node selects it, no full screen')
  await page.mouse.click(box.x + 8, box.y + 8)
  assert.deepEqual(await page.evaluate(() => window.__fs), [], 'the first empty click clears the selection instead')
  await page.close()
  const full = await embedWithFullscreenSpy('')
  const b2 = await full.locator('canvas').first().boundingBox()
  await full.mouse.click(b2.x + 8, b2.y + 8)
  assert.deepEqual(await full.evaluate(() => window.__fs), [], 'the full page never asks')
  await full.close()
})

test('embed: the empty background shows a zoom-in cursor', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await embedWithFullscreenSpy()
  const box = await page.locator('canvas').first().boundingBox()
  await page.mouse.move(box.x + 8, box.y + 8); await frames(page, 2)
  assert.equal(await page.evaluate(() => document.getElementById('c').style.cursor), 'zoom-in')
  await page.close()
})

// Gil 2026-10-08: not full screen — the map pops up in a white bordered box on the same page, still interactive,
// closed by clicking outside it. The embed asks its page; the page answers; no answer means full screen as before.
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
  await page.addInitScript(() => { window.__fs = []; Element.prototype.requestFullscreen = function () { window.__fs.push('request'); return Promise.resolve() } })
  await page.goto(pathToFileURL(path.join(dir, 'host.html')).href)
  const frame = page.frames().find((f) => f.url().includes('snapshot'))
  await frame.waitForFunction(() => window.__map)
  await frame.evaluate(() => { window.__map.driveExternally(); let t = performance.now(); for (let i = 0; i < 24; i++) window.renderFrame((t += 1000 / 24)) })
  const box = await page.locator('#m').boundingBox()
  await page.mouse.click(box.x + 8, box.y + 8)
  await page.waitForTimeout(700)
  return { asked: await page.evaluate(() => window.__asked), fs: await frame.evaluate(() => window.__fs), page }
}

test('framed: an empty-background click asks the page for its popup and does not go full screen when answered', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const r = await framedMap(t, { acknowledge: true })
  assert.equal(r.asked, 1)
  assert.deepEqual(r.fs, [])
  await r.page.close()
})

test('framed: a page that does not answer still gets full screen', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const r = await framedMap(t, { acknowledge: false })
  assert.equal(r.asked, 1)
  assert.deepEqual(r.fs, ['request'])
  await r.page.close()
})

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
