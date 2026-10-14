// MANUAL TEST SUITE: Full double-run browser lifecycle test
// =========================================================
//
// This suite runs the full test files twice to verify comprehensive browser cleanup under
// stress conditions. This is kept SEPARATE from the automated browser-lifecycle.test.mjs
// because running the same suite twice causes 1200s+ timeouts in CI.
//
// USE: Only run this manually for comprehensive verification:
//   node brain-map/tests/browser-lifecycle.manual.mjs
//
// Why separate?
// - Automated CI gate (browser-lifecycle.test.mjs) uses fast static guards + single-run leak check.
// - Manual suite does full stress testing (double-run each test file) for human verification.
// - Combining them would cause CI timeouts on every merge.

import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const MAP = path.resolve(HERE, '..')
const REPO_ROOT = path.resolve(MAP, '..')

// Helper: run a test file and return exit code
function runTest(testFile) {
  return new Promise((resolve, reject) => {
    const proc = spawn('node', ['--test', testFile], { cwd: REPO_ROOT })
    proc.on('close', (code) => resolve(code))
    proc.on('error', (e) => reject(e))
  })
}

const testFiles = [
  'brain-map/tests/snapshot.test.mjs',
  'brain-map/tests/labels.test.mjs',
  'brain-map/tests/code-layer.test.mjs'
]

async function runFullSuite() {
  console.log('MANUAL BROWSER LIFECYCLE STRESS TEST')
  console.log('==================================\n')
  console.log('Running each test file TWICE to stress-test browser cleanup.\n')

  let totalPassed = 0
  let totalFailed = 0

  for (let run = 1; run <= 2; run++) {
    console.log(`\n--- Run ${run}/2 ---\n`)

    for (const testFile of testFiles) {
      console.log(`Running ${testFile}...`)
      const code = await runTest(path.join(REPO_ROOT, testFile))

      if (code === 0) {
        console.log(`  ✓ PASS (exit code 0)\n`)
        totalPassed++
      } else {
        console.log(`  ✗ FAIL (exit code ${code})\n`)
        totalFailed++
      }
    }
  }

  console.log('\n==================================')
  console.log('RESULTS')
  console.log('==================================')
  console.log(`Passed: ${totalPassed}/${testFiles.length * 2}`)
  console.log(`Failed: ${totalFailed}/${testFiles.length * 2}`)

  if (totalFailed > 0) {
    process.exit(1)
  } else {
    console.log('\n✓ All tests passed! Browser cleanup is stable under stress.')
    process.exit(0)
  }
}

runFullSuite().catch(err => {
  console.error('Error running test suite:', err)
  process.exit(1)
})
