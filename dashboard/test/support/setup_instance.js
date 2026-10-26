import { execSync } from 'child_process'
import { mkdtempSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'
import * as instance from '../../electron/main/instance.js'
import { beforeEach, afterEach } from 'vitest'

// All JS tests run against a default configured instance with a fake GitHub origin.
// This matches the Python test setup (lib/tests/conftest.py) so that instance.requireConfigured()
// does not fail or read the real ~/.agents/instance.

let testEngineDir = null

beforeEach(() => {
  if (!testEngineDir) {
    // Create once per test run, reuse across tests.
    testEngineDir = mkdtempSync(path.join(os.tmpdir(), 'marvin-test-engine-'))
    try {
      execSync(`git init -q "${testEngineDir}"`)
      execSync(`git -C "${testEngineDir}" remote add origin "https://github.com/test-owner/marvin.git"`)
    } catch (e) {
      console.error('Failed to set up test engine dir:', e.message)
      throw e
    }
  }

  // Point instance.js at the temp engine dir for this test.
  process.env.MARVIN_ENGINE_DIR = testEngineDir
  // Point MARVIN_INSTANCE_DIR to the temp home's .agents/instance (created by temp_home.js).
  process.env.MARVIN_INSTANCE_DIR = path.join(process.env.HOME, '.agents', 'instance')
  instance.reset()
})

afterEach(() => {
  instance.reset()
})
