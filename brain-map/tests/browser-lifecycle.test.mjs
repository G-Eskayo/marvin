// Browser lifecycle management (#189): detecting leaks and testing proper cleanup.
//
// Guard tests 23-28: Static source-text regex checks that each test file has proper browser cleanup.
// Test 13: Lightweight in-process leak-regression check (single run, not double-run).
//
// Run: node --test brain-map/tests/browser-lifecycle.test.mjs
//
// NOTE: The full double-run browser leak test suite is in browser-lifecycle.manual.mjs,
// kept separate because running the same suite twice causes 1200s+ timeouts in CI.
// Use that script only for manual verification of comprehensive leak coverage.

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const MAP = path.resolve(HERE, '..')
const REPO_ROOT = path.resolve(MAP, '..')

// Helper: run a test file and return exit code
function runTest(testFile) {
  return new Promise((resolve, reject) => {
    const proc = spawn('node', ['--test', testFile], { cwd: REPO_ROOT, timeout: 60000 })
    proc.on('close', (code) => resolve(code))
    proc.on('error', (e) => reject(e))
  })
}

// Helper: read source file and check for proper browser cleanup patterns
function checkBrowserCleanup(filePath, testName) {
  const source = readFileSync(filePath, 'utf8')

  // Check for chromium.launch() with channel: 'chrome' (required for real Chrome, not playwright-core)
  const launchMatch = source.match(/chromium\.launch\(\s*{[^}]*channel:\s*['"]chrome['"][^}]*}/i)
  assert.ok(launchMatch, `${testName}: Missing chromium.launch({ channel: 'chrome' })`)

  // Check for proper cleanup patterns:
  // - browser.close() or await browser.close()
  // - try/finally with close in finally
  // - async with or similar pattern
  const hasCloseCall = /\bbrowser\.close\(\)/.test(source)
  const hasAwaitClose = /\bawait\s+.*\.close\(\)/.test(source)
  const hasTryFinally = /try\s*{[\s\S]*?finally\s*{[\s\S]*?\.close\(\)/.test(source)
  const hasAsyncWith = /async\s+with|with\s+\(.*browser/.test(source)

  const hasProperCleanup = hasCloseCall || hasAwaitClose || hasTryFinally || hasAsyncWith
  assert.ok(hasProperCleanup,
    `${testName}: Missing proper browser cleanup (close call, try/finally, or async with)`)
}

// Guard tests 23-28: Static source-text checks (fast, no process spawning)

test('guard 23: snapshot.test.mjs has chromium.launch({ channel: "chrome" })', () => {
  checkBrowserCleanup(path.join(MAP, 'tests', 'snapshot.test.mjs'), 'snapshot.test.mjs')
})

test('guard 24: labels.test.mjs has chromium.launch({ channel: "chrome" })', () => {
  checkBrowserCleanup(path.join(MAP, 'tests', 'labels.test.mjs'), 'labels.test.mjs')
})

test('guard 25: code-layer.test.mjs has chromium.launch({ channel: "chrome" })', () => {
  checkBrowserCleanup(path.join(MAP, 'tests', 'code-layer.test.mjs'), 'code-layer.test.mjs')
})

test('guard 26: snapshot.test.mjs has cleanup in try/finally or similar', () => {
  const source = readFileSync(path.join(MAP, 'tests', 'snapshot.test.mjs'), 'utf8')
  const hasFinally = /finally\s*{[\s\S]*?close\(\)/.test(source)
  const hasAwaitClose = /await\s+.*\.close\(\)/.test(source)
  assert.ok(hasFinally || hasAwaitClose, 'Missing finally block or await on close()')
})

test('guard 27: labels.test.mjs has cleanup in try/finally or similar', () => {
  const source = readFileSync(path.join(MAP, 'tests', 'labels.test.mjs'), 'utf8')
  const hasFinally = /finally\s*{[\s\S]*?close\(\)/.test(source)
  const hasAwaitClose = /await\s+.*\.close\(\)/.test(source)
  assert.ok(hasFinally || hasAwaitClose, 'Missing finally block or await on close()')
})

test('guard 28: code-layer.test.mjs has cleanup in try/finally or similar', () => {
  const source = readFileSync(path.join(MAP, 'tests', 'code-layer.test.mjs'), 'utf8')
  const hasFinally = /finally\s*{[\s\S]*?close\(\)/.test(source)
  const hasAwaitClose = /await\s+.*\.close\(\)/.test(source)
  assert.ok(hasFinally || hasAwaitClose, 'Missing finally block or await on close()')
})

// Test 13: Lightweight in-process leak-regression check
test('test 13: fast leak-regression check - no orphaned chromium processes remain', async (t) => {
  t.timeout(30000)
  // Import here to avoid hanging during test setup
  const { execSync } = await import('node:child_process')

  // List chromium processes before running tests
  let before, after
  try {
    before = execSync('pgrep chromium 2>/dev/null | wc -l', { shell: true, encoding: 'utf8' }).trim()
  } catch {
    before = '0'
  }

  // Run one test that opens a browser
  const code = await runTest(path.join(MAP, 'tests', 'snapshot.test.mjs'))
  assert.equal(code, 0, 'snapshot.test.mjs failed')

  // Check processes after
  try {
    after = execSync('pgrep chromium 2>/dev/null | wc -l', { shell: true, encoding: 'utf8' }).trim()
  } catch {
    after = '0'
  }

  // Leak: processes increased after running the test
  const leaked = parseInt(after) - parseInt(before)
  assert.equal(leaked, 0, `${leaked} chromium process(es) leaked after running snapshot.test.mjs`)
})
