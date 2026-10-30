// Truthful motion on the live map (#843): nothing on the map moves unless something real happened.
//
// The rule, decided with Gil 2026-10-29: a node lights from its own work rate, a leaf lights when it's touched and
// its region shows it, a link lights only from traffic across it (an event naming both ends, or the causal pair in
// the page: a skill call, then the next event in the same session within the window, on a node that skill has a
// thread to), pulses take at least 1.5 s and batch under load, idle parts are still, the camera never moves by
// itself, a failure stays red until a pass, and Reduce Motion keeps only brightness changes.
//
// Frames are driven from here through window.renderFrame at a fixed step, the way DesktopLive drives the
// wallpaper, so results don't depend on timing. The page's clock for events is the last frame's time.
//
// Run: node --test brain-map/tests/motion.test.mjs   (regenerates index.html first)
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

const STEP = 1000 / 24 // DesktopLive's frame interval
const SECOND = 24
// Real nodes and a real thread from the generated tree: grill-with-docs `calls:` grill-me, and lexicon.
const CALLER = 'grill-with-docs', CALLEE = 'grill-me', LEAF = 'tdd'

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

async function openMap({ wallpaper = false, reducedMotion = 'no-preference', countRaf = false } = {}) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, reducedMotion })
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  if (countRaf) {
    await page.addInitScript(() => {
      window.__rafCalls = 0
      const real = window.requestAnimationFrame.bind(window)
      window.requestAnimationFrame = (cb) => { window.__rafCalls++; return real(cb) }
    })
  }
  await page.goto(pathToFileURL(path.join(MAP, 'index.html')).href + (wallpaper ? '?wallpaper=1' : ''))
  if (!wallpaper) await page.evaluate(() => window.__map.driveExternally())
  page.errors = errors
  return page
}

const frames = (page, n) => page.evaluate(([n, step]) => {
  window.__t = window.__t || performance.now()
  for (let i = 0; i < n; i++) window.renderFrame((window.__t += step))
}, [n, STEP])

// An event, stamped with the page's own clock (seconds) unless the test gives one.
const send = (page, ev) => page.evaluate((ev) => {
  const now = (window.__t || performance.now())
  window.triggerActivity(Object.assign({ ts: 1.7e9 + now / 1000 }, ev))
}, ev)

const pixels = (page) => page.evaluate(() => document.getElementById('c').toDataURL())
const camera = (page) => page.evaluate(() => window.__map.camera())

for (const wallpaper of [false, true]) {
  test(`${wallpaper ? 'wallpaper' : 'browser'}: with no events for 60 s nothing on the canvas moves`, async (t) => {
    if (skipReason) return t.skip(skipReason)
    const page = await openMap({ wallpaper })
    await send(page, { skill: LEAF, tool: 'Skill', session: 's1' }) // something real happened once, then nothing
    await frames(page, 60 * SECOND)
    const a = await pixels(page), camA = await camera(page)
    await frames(page, 3 * SECOND)
    const b = await pixels(page), camB = await camera(page)
    assert.deepEqual(camB, camA, 'the camera moved with nothing happening')
    assert.ok(a === b, 'the canvas changed between two idle frames 3 s apart')
    assert.equal(await page.evaluate(() => window.__map.autoRotate()), false, 'auto-rotate is on by default')
    assert.deepEqual(page.errors, [])
    await page.close()
  })
}

test('an event on a leaf lights that leaf, and the branch up to its region shows it', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, 2)
  assert.equal(await page.evaluate((id) => window.__map.level(id), LEAF), 0, 'the leaf is lit before anything happened')
  await send(page, { skill: LEAF, tool: 'Skill', session: 's1' })
  await frames(page, 2)
  const lit = await page.evaluate((id) => {
    let parent = window.__map.parentOf(id)
    return { leaf: window.__map.level(id), region: window.__map.region(id), parent, parentRegion: window.__map.region(parent) }
  }, LEAF)
  assert.ok(lit.leaf > 0.3, `leaf brightness ${lit.leaf}`)
  assert.ok(lit.region > 0.3, `the branch into the leaf is not lit: ${lit.region}`)
  assert.ok(lit.parentRegion > 0, `the region (${lit.parent}) does not show the leaf's activity`)
  await page.close()
})

test('brightness follows the rate: more work in the window is brighter, and it fades back to exactly zero', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, 1)
  await send(page, { skill: LEAF })
  await frames(page, 1)
  const one = await page.evaluate((id) => window.__map.level(id), LEAF)
  for (let i = 0; i < 5; i++) await send(page, { skill: LEAF })
  await frames(page, 1)
  const six = await page.evaluate((id) => window.__map.level(id), LEAF)
  assert.ok(six > one, `six events (${six}) not brighter than one (${one})`)
  await frames(page, 60 * SECOND)
  assert.equal(await page.evaluate((id) => window.__map.level(id), LEAF), 0)
  await page.close()
})

test('a touched file lights the node that owns it, and in an open code layer the file and its functions', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, 1)
  await send(page, { skill: 'MARVIN', tool: 'Edit', file: 'skills/tdd/SKILL.md', session: 's1' })
  await frames(page, 1)
  assert.ok(await page.evaluate(() => window.__map.level('tdd')) > 0.3, 'editing a skill file did not light the skill')
  assert.equal(await page.evaluate(() => window.__map.level('MARVIN')), 0, 'the root lit for a file that has an owner')

  const owner = await page.evaluate(() => window.__map.codeOwnerWithFile())
  assert.ok(owner, 'no node in the tree has code with a source file')
  await page.evaluate((id) => window.__map.open(id), owner.node)
  await send(page, { skill: 'MARVIN', tool: 'Read', file: owner.file })
  await frames(page, 1)
  const code = await page.evaluate((ids) => ids.map((id) => window.__map.level(id)), owner.ids)
  assert.ok(code.length > 1 && code.every((l) => l > 0.3), `code nodes in ${owner.file} not all lit: ${code}`)
  await page.close()
})

test('a single-node event lights no link', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, 1)
  await send(page, { skill: CALLER, tool: 'Skill', session: 's1' })
  await send(page, { skill: CALLEE, tool: 'Skill' }) // no session: can't be paired with anything
  await send(page, { skill: 'MARVIN', tool: 'Bash', session: 's1' }) // the root has no thread from the caller
  await frames(page, SECOND)
  assert.deepEqual(await page.evaluate(() => window.__map.links()), [])
  assert.deepEqual(await page.evaluate(() => window.__map.pulses()), [])
  await page.close()
})

test('a skill call then an event in the same session on a node it has a thread to lights that link, caller to callee', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, 1)
  const ts = 1.8e9
  await send(page, { skill: CALLER, tool: 'Skill', session: 's1', ts })
  await send(page, { skill: CALLEE, tool: 'Skill', session: 's1', ts: ts + 5 })
  await frames(page, 2)
  const links = await page.evaluate(() => window.__map.links())
  assert.equal(links.length, 1, JSON.stringify(links))
  assert.deepEqual([links[0].a, links[0].b].sort(), [CALLER, CALLEE].sort())
  assert.ok(links[0].level > 0.3)
  const pulses = await page.evaluate(() => window.__map.pulses())
  assert.equal(pulses.length, 1)
  assert.equal(pulses[0].from, CALLER)
  assert.equal(pulses[0].to, CALLEE)
  await page.close()
})

test('no link from a pair in different sessions, out of order, or outside the window', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, 1)
  const ts = 1.8e9
  await send(page, { skill: CALLER, tool: 'Skill', session: 'a', ts })
  await send(page, { skill: CALLEE, tool: 'Skill', session: 'b', ts: ts + 1 }) // another session
  await send(page, { skill: CALLER, tool: 'Skill', session: 'c', ts })
  await send(page, { skill: CALLEE, tool: 'Skill', session: 'c', ts: ts - 3 }) // stamped before its cause
  await send(page, { skill: CALLER, tool: 'Skill', session: 'd', ts })
  await send(page, { skill: CALLEE, tool: 'Skill', session: 'd', ts: ts + 600 }) // ten minutes later
  await frames(page, SECOND)
  assert.deepEqual(await page.evaluate(() => window.__map.links()), [])
  await page.close()
})

test('a pulse takes at least 1.5 s to cross, at any event rate', async (t) => {
  if (skipReason) return t.skip(skipReason)
  for (const storm of [false, true]) {
    const page = await openMap()
    await frames(page, 1)
    const n = storm ? 200 : 1
    await page.evaluate(([n, a, b]) => {
      for (let i = 0; i < n; i++) {
        window.triggerActivity({ skill: a, tool: 'Skill', session: 's' + i, ts: 1.8e9 + i * 0.001 })
        window.triggerActivity({ skill: b, tool: 'Skill', session: 's' + i, ts: 1.8e9 + i * 0.001 + 1 })
      }
    }, [n, CALLER, CALLEE])
    await frames(page, 1)
    const first = (await page.evaluate(() => window.__map.pulses()))[0]
    assert.ok(first, 'no pulse launched')
    await frames(page, Math.floor(1.45 * SECOND))
    const still = (await page.evaluate(() => window.__map.pulses())).find((p) => p.id === first.id)
    assert.ok(still && still.progress < 1, `the pulse arrived in under 1.5 s (storm=${storm})`)
    await page.close()
  }
})

test('an event storm (1,000 events in 10 s): frame rate holds, pulses batch, the legend says so, the camera stays', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, SECOND)
  const cam = await camera(page)
  const worst = await page.evaluate(([a, b, step]) => {
    let slowest = 0, sent = 0
    for (let f = 0; f < 240; f++) { // 10 s of frames, ~4 events each, half of them causal pairs
      for (let k = 0; k < 4 && sent < 1000; k++, sent++) {
        const ts = 1.8e9 + sent * 0.01
        window.triggerActivity(sent % 2 ? { skill: b, tool: 'Skill', session: 'storm', ts } : { skill: a, tool: 'Skill', session: 'storm', ts })
      }
      const t0 = performance.now()
      window.renderFrame((window.__t += step))
      slowest = Math.max(slowest, performance.now() - t0)
    }
    return slowest
  }, [CALLER, CALLEE, STEP])
  assert.ok(worst < 1000 / 24, `slowest frame ${worst.toFixed(1)} ms, over the 24 fps budget`)
  const pulses = await page.evaluate(() => window.__map.pulses())
  assert.ok(pulses.length > 0 && pulses.length <= 4, `${pulses.length} pulses in flight on one link`)
  const n = Math.max(...pulses.map((p) => p.n))
  assert.ok(n > 1, 'pulses did not batch')
  const note = await page.evaluate(() => window.__map.legendNote())
  assert.match(note, new RegExp(`1 pulse = up to ${n} events`))
  assert.deepEqual(await camera(page), cam, 'the camera moved during the storm')
  await frames(page, 30 * SECOND)
  assert.equal(await page.evaluate(() => window.__map.legendNote()), '', 'the batching note stayed after the storm')
  await page.close()
})

test('events for nodes that do not exist are ignored and draw no phantom node', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, 2)
  const before = await page.evaluate(() => window.__map.nodes().length)
  await send(page, { skill: 'no-such-skill', tool: 'Skill', session: 's1' })
  await send(page, { skill: 'no-such-skill', tool: 'Edit', file: 'nowhere/at/all.py', session: 's1' })
  await page.evaluate(() => { window.triggerActivity('another-ghost'); window.triggerActivity(null); window.triggerActivity({}) })
  await frames(page, 2)
  assert.equal(await page.evaluate(() => window.__map.nodes().length), before)
  assert.equal(await page.evaluate(() => window.__map.level('no-such-skill')), 0)
  assert.equal((await page.evaluate(() => window.__map.tray())).count, 0, 'a ghost event went into the tray')
  assert.deepEqual(page.errors, [])
  await page.close()
})

test('out-of-order timestamps and clock skew: polled lines are still read, and still light', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, 1)
  // The first read is history: it must not replay.
  const history = [{ skill: LEAF, ts: 1.8e9 }].map((o) => JSON.stringify(o)).join('\n')
  await page.evaluate((text) => window.__map.ingestLines(text), history)
  await frames(page, 1)
  assert.equal(await page.evaluate((id) => window.__map.level(id), LEAF), 0, 'history replayed on load')
  // A new line stamped earlier than everything seen so far (another Mac's clock is behind), then one far ahead.
  const later = history + '\n' + JSON.stringify({ skill: CALLER, ts: 1.7e9 }) + '\n' + JSON.stringify({ skill: CALLEE, ts: 1.9e9 })
  await page.evaluate((text) => window.__map.ingestLines(text), later)
  await frames(page, 1)
  assert.ok(await page.evaluate((id) => window.__map.level(id), CALLER) > 0, 'a line stamped in the past was dropped')
  assert.ok(await page.evaluate((id) => window.__map.level(id), CALLEE) > 0, 'a line stamped in the future was dropped')
  // Reading the same file again changes nothing.
  await frames(page, 60 * SECOND)
  await page.evaluate((text) => window.__map.ingestLines(text), later)
  await frames(page, 1)
  assert.equal(await page.evaluate((id) => window.__map.level(id), CALLER), 0, 'a line already read fired again')
  await page.close()
})

test('a failure turns the node red and lights the links to what depends on it, until a pass', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, 1)
  await send(page, { skill: CALLEE, tool: 'Skill', ok: false })
  await frames(page, 60 * SECOND) // red stays, not a pulse
  assert.equal(await page.evaluate((id) => window.__map.failed(id), CALLEE), true)
  const red = (await page.evaluate(() => window.__map.links())).filter((l) => l.failed)
  assert.ok(red.some((l) => l.a === CALLER && l.b === CALLEE), `the caller's thread to the failed node is not lit: ${JSON.stringify(red)}`)
  // still: a red node doesn't move either
  const a = await pixels(page); await frames(page, SECOND); assert.ok(a === (await pixels(page)), 'a red node animates')
  await send(page, { skill: CALLEE, tool: 'Skill', ok: true })
  await frames(page, 1)
  assert.equal(await page.evaluate((id) => window.__map.failed(id), CALLEE), false)
  assert.equal((await page.evaluate(() => window.__map.links())).filter((l) => l.failed).length, 0)
  await page.close()
})

test('Reduce Motion: links still brighten but no pulse travels', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap({ reducedMotion: 'reduce' })
  await frames(page, 1)
  await send(page, { skill: CALLER, tool: 'Skill', session: 's1', ts: 1.8e9 })
  await send(page, { skill: CALLEE, tool: 'Skill', session: 's1', ts: 1.8e9 + 1 })
  await frames(page, 2)
  assert.equal((await page.evaluate(() => window.__map.links())).length, 1)
  assert.deepEqual(await page.evaluate(() => window.__map.pulses()), [])
  await page.close()
})

test('wallpaper mode never uses requestAnimationFrame: events and pulses advance on the host\'s renderFrame clock', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap({ wallpaper: true, countRaf: true })
  await page.waitForTimeout(300)
  // The page never asks for animation frames itself: DesktopLive's timer is its only clock.
  assert.equal(await page.evaluate(() => window.__rafCalls), 0)
  await frames(page, 1)
  // The macOS host passes each activity line through whole (main.swift checkForActivity).
  await page.evaluate(([a, b]) => {
    window.triggerActivity({ skill: a, tool: 'Skill', session: 'w', ts: 1.8e9 })
    window.triggerActivity({ skill: b, tool: 'Skill', session: 'w', ts: 1.8e9 + 1 })
  }, [CALLER, CALLEE])
  await page.waitForTimeout(2000) // real time passes with no renderFrame call: nothing advances
  await frames(page, 1)
  const p = (await page.evaluate(() => window.__map.pulses()))[0]
  assert.ok(p && p.progress < 0.1, `the pulse advanced without the host's clock: ${JSON.stringify(p)}`)
  await frames(page, 2 * SECOND)
  assert.deepEqual(await page.evaluate(() => window.__map.pulses()), [], 'the pulse never finished on the host clock')
  assert.equal(await page.evaluate(() => window.__rafCalls), 0)
  await page.close()
})

test('the tray counts what happened in the last minute, and tapping an item focuses its node (the only camera move)', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, 1)
  for (let i = 0; i < 11; i++) await send(page, { skill: LEAF, tool: 'Skill' })
  await send(page, { skill: CALLEE, tool: 'Skill' })
  await frames(page, 1)
  let tray = await page.evaluate(() => window.__map.tray())
  assert.equal(tray.count, 12)
  assert.equal(tray.visible, true)
  assert.match(tray.text, /^12 things happened in the last minute$/)
  const cam = await camera(page)
  await page.click('#event-tray-toggle')
  await page.click(`#event-tray-list [data-node="${CALLEE}"]`)
  await frames(page, 2 * SECOND)
  assert.notDeepEqual(await camera(page), cam, 'tapping an item did not focus its node')
  const settled = await camera(page)
  await frames(page, 2 * SECOND)
  assert.deepEqual(await camera(page), settled, 'the camera kept moving after the focus ease')
  await frames(page, 60 * SECOND)
  tray = await page.evaluate(() => window.__map.tray())
  assert.equal(tray.count, 0)
  assert.equal(tray.visible, false)
  await page.close()
})

test('auto-rotate is a toggle, off by default', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, SECOND)
  const cam = await camera(page)
  await page.click('#auto-rotate-toggle')
  await frames(page, SECOND)
  assert.notEqual((await camera(page)).yaw, cam.yaw, 'the toggle did not turn rotation on')
  await page.click('#auto-rotate-toggle')
  const off = await camera(page)
  await frames(page, SECOND)
  assert.deepEqual(await camera(page), off)
  await page.close()
})

test('a device appearing or a demo node being added animates the node but does not move the camera', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  await frames(page, SECOND)
  const cam = await camera(page)
  await page.evaluate(() => window.demoAddNode({ id: 'demo-x', cat: 'other' }, 'Memory'))
  await frames(page, 5 * SECOND)
  assert.deepEqual(await camera(page), cam)
  await page.close()
})
