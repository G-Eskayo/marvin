// Code layer opening/closing (#184, ADR 0049).
//
// Tests that openable nodes (skills, agents, hooks, dashboard tabs) can be
// opened to view their code layer, with proper camera easing, system layer
// fading, and close affordances (Esc key + back button).
//
// Frames are driven from here through window.renderFrame at a fixed step, the
// same way DesktopLive drives the wallpaper, so results don't depend on timing.
//
// Run: node --test brain-map/tests/code-layer.test.mjs   (regenerates index.html first)
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
const SETTLE = 24 // one second of frames

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

async function openMap(width = 1280, height = 800) {
  const page = await browser.newPage({ viewport: { width, height } })
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto(pathToFileURL(path.join(MAP, 'index.html')).href)
  await page.evaluate(() => window.__map.driveExternally())
  assert.deepEqual(errors, [])
  return page
}

const frames = (page, n) => page.evaluate(([n, step]) => {
  window.__t = window.__t || performance.now()
  for (let i = 0; i < n; i++) window.renderFrame((window.__t += step))
}, [n, STEP])

test('opening an openable node sets openNodeId and shows code-layer-note', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const result = await page.evaluate(() => {
    window.__map.setCamera(0.6, -0.2)
    const allNodes = window.__map.nodes()
    const openable = allNodes.find(n => n.openable)
    if (!openable) return { found: false }
    window.__map.open(openable.id)
    return { found: true, nodeId: openable.id }
  })
  await frames(page, SETTLE)
  assert.ok(result.found, 'no openable nodes found')
  const openId = await page.evaluate(() => window.__map.openId())
  assert.equal(openId, result.nodeId, 'openNodeId not set')
  const noteVisible = await page.evaluate(() => {
    const note = document.getElementById('code-layer-note')
    return note.classList.contains('show')
  })
  assert.ok(noteVisible, 'code-layer-note not visible')
})

test('clicking an openable node twice toggles it closed', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const result = await page.evaluate(() => {
    const allNodes = window.__map.nodes()
    const openable = allNodes.find(n => n.openable)
    if (!openable) return { found: false }
    window.__map.open(openable.id)
    window.renderFrame(performance.now())
    const afterOpen = window.__map.openId()
    window.__map.open(openable.id)
    window.renderFrame(performance.now())
    const afterClose = window.__map.openId()
    return { found: true, openedCorrectly: afterOpen === openable.id, closedCorrectly: afterClose === null }
  })
  assert.ok(result.found, 'no openable nodes found')
  assert.ok(result.openedCorrectly, 'node did not open')
  assert.ok(result.closedCorrectly, 'node did not close')
})

test('Esc key closes code layer', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  // Open a node
  await page.evaluate(() => {
    const allNodes = window.__map.nodes()
    const openable = allNodes.find(n => n.openable)
    if (openable) window.__map.open(openable.id)
  })
  await frames(page, SETTLE)
  // Press Escape
  await page.keyboard.press('Escape')
  await frames(page, SETTLE)
  const openId = await page.evaluate(() => window.__map.openId())
  assert.equal(openId, null, 'Esc did not close code layer')
})

test('back button closes code layer', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  // Open a node
  await page.evaluate(() => {
    const allNodes = window.__map.nodes()
    const openable = allNodes.find(n => n.openable)
    if (openable) window.__map.open(openable.id)
  })
  await frames(page, SETTLE)
  // Click back button
  await page.click('#code-close')
  await frames(page, SETTLE)
  const openId = await page.evaluate(() => window.__map.openId())
  assert.equal(openId, null, 'back button did not close code layer')
})

test('only one node can be open at a time', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const result = await page.evaluate(() => {
    const allNodes = window.__map.nodes()
    const openable = allNodes.filter(n => n.openable)
    if (openable.length < 2) return { skip: true }
    const first = openable[0]
    const second = openable[1]
    window.__map.open(first.id)
    window.renderFrame(performance.now())
    const afterFirst = window.__map.openId()
    window.__map.open(second.id)
    window.renderFrame(performance.now())
    const afterSecond = window.__map.openId()
    return {
      skip: false,
      firstCorrect: afterFirst === first.id,
      secondCorrect: afterSecond === second.id,
      onlyOneOpen: afterSecond !== first.id
    }
  })
  if (result.skip) return t.skip('fewer than 2 openable nodes in test tree')
  assert.ok(result.firstCorrect, 'first node did not open correctly')
  assert.ok(result.secondCorrect, 'second node did not open correctly')
  assert.ok(result.onlyOneOpen, 'both nodes were open at the same time')
})

test('openable nodes have code layer data attached', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const result = await page.evaluate(() => {
    const allNodes = window.__map.nodes()
    const openable = allNodes.filter(n => n.openable)
    if (openable.length === 0) return { skip: true }
    const hasCodeData = openable.every(n => n.code && typeof n.code === 'object' &&
      ('files' in n.code && 'functions' in n.code && 'edges' in n.code && 'borrowed' in n.code))
    return { skip: false, hasCodeData }
  })
  if (result.skip) return t.skip('no openable nodes in test tree')
  assert.ok(result.hasCodeData, 'openable nodes missing code layer data')
})

test('code layer data has correct structure', async (t) => {
  if (skipReason) return t.skip(skipReason)
  const page = await openMap()
  const result = await page.evaluate(() => {
    const allNodes = window.__map.nodes()
    const openable = allNodes.find(n => n.openable)
    if (!openable) return { skip: true }
    const code = openable.code
    const filesValid = Array.isArray(code.files) && code.files.every(f => f.id && f.label && f.community !== undefined)
    const functionsValid = Array.isArray(code.functions) && code.functions.every(f => f.id && f.label && f.community !== undefined)
    const edgesValid = Array.isArray(code.edges)
    const borrowedValid = Array.isArray(code.borrowed)
    return {
      skip: false,
      filesValid,
      functionsValid,
      edgesValid,
      borrowedValid
    }
  })
  if (result.skip) return t.skip('no openable nodes in test tree')
  assert.ok(result.filesValid, 'files in code layer have incorrect structure')
  assert.ok(result.functionsValid, 'functions in code layer have incorrect structure')
  assert.ok(result.edgesValid, 'edges in code layer not an array')
  assert.ok(result.borrowedValid, 'borrowed nodes in code layer not an array')
})
