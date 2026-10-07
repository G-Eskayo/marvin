// Labels and clipping on the brain-map page (#183, ADR 0049).
//
// The page draws labels by priority, only where their screen box is free and
// their node isn't hidden behind a nearer one. This checks the labels actually
// drawn (not that every label is visible) at three screen widths and several
// camera angles, in the browser and on the wallpaper, plus that no node is
// clipped and the legend leaves the intro text readable.
//
// Frames are driven from here through window.renderFrame at a fixed step, the
// same way DesktopLive drives the wallpaper, so results don't depend on timing.
//
// Run: node --test brain-map/tests/labels.test.mjs   (regenerates index.html first)
import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const MAP = path.resolve(HERE, '..')
const AGENTS = path.resolve(MAP, '..')
// playwright-core is already a dashboard dev dependency; borrow it rather than add another install.
const { chromium } = createRequire(path.join(AGENTS, 'dashboard', 'package.json'))('playwright-core')

const SCREENS = [[1280, 800], [1920, 1080], [2560, 1440]]
const ANGLES = [[0.6, -0.2], [0, 0], [1.6, 0.3], [3.1, -0.6], [4.4, 0.9], [5.5, -1.2]]
const STEP = 1000 / 24 // DesktopLive's frame interval
const SETTLE = 48 // two seconds of frames: fades finish and the wallpaper fit settles

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

async function openMap([width, height], wallpaper) {
  const page = await browser.newPage({ viewport: { width, height } })
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto(pathToFileURL(path.join(MAP, 'index.html')).href + (wallpaper ? '?wallpaper=1' : ''))
  await page.evaluate(() => window.__map.driveExternally())
  assert.deepEqual(errors, [])
  return page
}

const frames = (page, n) => page.evaluate(([n, step]) => {
  window.__t = window.__t || performance.now()
  for (let i = 0; i < n; i++) window.renderFrame((window.__t += step))
}, [n, STEP])

const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h

for (const wallpaper of [false, true]) {
  for (const screen of SCREENS) {
    test(`${wallpaper ? 'wallpaper' : 'browser'} at ${screen[0]}px: drawn labels never overlap and no node is clipped`, async (t) => {
      if (skipReason) return t.skip(skipReason)
      const page = await openMap(screen, wallpaper)
      for (const [yaw, pitch] of ANGLES) {
        await page.evaluate(([y, p]) => window.__map.setCamera(y, p), [yaw, pitch])
        await frames(page, SETTLE)
        // Labels holding a place; one giving its place up fades out over a few frames.
        const labels = (await page.evaluate(() => window.__map.labels())).filter((l) => l.shown)
        assert.ok(labels.length >= 10, `only ${labels.length} labels drawn at yaw ${yaw}`)
        for (let i = 0; i < labels.length; i++) {
          for (let j = i + 1; j < labels.length; j++) {
            assert.ok(!overlaps(labels[i], labels[j]),
              `"${labels[i].text}" and "${labels[j].text}" overlap at yaw ${yaw}, pitch ${pitch}`)
          }
        }
        for (const n of await page.evaluate(() => window.__map.nodes())) {
          assert.ok(n.sx - n.r >= 0 && n.sx + n.r <= screen[0] && n.sy - n.r >= 0 && n.sy + n.r <= screen[1],
            `${n.id} is clipped at yaw ${yaw}, pitch ${pitch} (${Math.round(n.sx)}, ${Math.round(n.sy)})`)
        }
      }
      await page.close()
    })
  }
}

for (const screen of SCREENS) {
  test(`the legend leaves the intro text readable at ${screen[0]}px`, async (t) => {
    if (skipReason) return t.skip(skipReason)
    const page = await openMap(screen, false)
    const [intro, legend] = await page.evaluate(() =>
      ['header p', '#legend'].map((s) => { const r = document.querySelector(s).getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height } }))
    assert.ok(!overlaps(intro, legend), `legend ${JSON.stringify(legend)} covers intro ${JSON.stringify(intro)}`)
    await page.close()
  })
}

test('labels fade in and out rather than pop', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap([1920, 1080], false)
  await page.evaluate(() => window.__map.setCamera(0.6, -0.2))
  await frames(page, SETTLE)
  const before = new Map((await page.evaluate(() => window.__map.labels())).map((l) => [l.text, l.alpha]))

  await page.evaluate(() => window.__map.setCamera(3.1, -0.6))
  await frames(page, 1)
  const after = await page.evaluate(() => window.__map.labels())
  const partWay = (l) => l.alpha > 0 && l.alpha < 1
  assert.ok(after.some((l) => !before.has(l.text) && partWay(l)), 'no label part-way through fading in one frame after the camera jumped')
  assert.ok(after.some((l) => before.get(l.text) === 1 && partWay(l)), 'no label part-way through fading out one frame after the camera jumped')
  await page.close()
})

test('a regenerated tree pushed live (DesktopLive\'s updateTreeData) takes the positions it carries', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap([1920, 1080], true)
  const moved = await page.evaluate(() => {
    const tree = { id: 'MARVIN', cat: 'root', children: [
      { id: 'Memory', cat: 'memory', pos: [0, -140, 0], children: [] },
      { id: 'Projects', cat: 'projects', pos: [140, 0, 0], children: [] },
    ], pos: [0, 0, 0] }
    window.updateTreeData(tree, [])
    window.__map.setCamera(0, 0)
    let t = performance.now(); for (let i = 0; i < 48; i++) window.renderFrame(t += 1000 / 24)
    return Object.fromEntries(window.__map.nodes().map((n) => [n.id, [n.sx, n.sy]]))
  })
  // At yaw 0, pitch 0: +y in the layout is down the screen, +x is right of centre. 15 px allows for the idle sway.
  assert.ok(moved.Memory[1] < moved.MARVIN[1] - 50 && Math.abs(moved.Memory[0] - moved.MARVIN[0]) < 15, JSON.stringify(moved))
  assert.ok(moved.Projects[0] > moved.MARVIN[0] + 50 && Math.abs(moved.Projects[1] - moved.MARVIN[1]) < 15, JSON.stringify(moved))
  await page.close()
})
