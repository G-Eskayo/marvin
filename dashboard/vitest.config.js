import { resolve } from 'node:path'
import { makeTestHome, removeTestHome } from './test/support/temp_home.js'
import { takeSlotForVitest } from './webhook-server/test_slot.js'


// Tests never touch the real ~/.claude (test/support/temp_home.js). Set here, in the main process, before any worker
// starts, so every worker and child process inherits it; each test file then checks it (setupFiles) and fails closed.
if (!process.env.MARVIN_TEST_HOME) {
  const home = makeTestHome()
  process.env.MARVIN_TEST_HOME = home
  process.env.HOME = home
  process.on('exit', () => { try { removeTestHome(home) } catch { /* left for the OS to clear from tmp */ } })
}

// marvin#940: one test run at a time on this machine, merges first (lib/test_slot.py). A whole run waits for the slot
// here, before any worker starts; a run of one file never waits. Inside the merge gate the slot is already held.
export default async () => {
  await takeSlotForVitest()
  return config
}

// Tests render React components to static HTML (react-dom/server); the app's own build uses the
// automatic JSX runtime (electron.vite.config.js), so the tests must too.
const config = {
  esbuild: { jsx: 'automatic' },
  // Same aliases as the app's renderer build, so a test can render App.jsx.
  resolve: { alias: { '@': resolve(import.meta.dirname, 'src'), '@components': resolve(import.meta.dirname, 'src/components') } },
  test: {
    setupFiles: ['./test/support/assert_temp_home.js'],
    // A hung test fails fast, by name (pipeline review 2026-10-21, F3). Vitest's own defaults, stated so nobody
    // raises them without seeing this: 5 s per test (a test that needs longer says so itself), 10 s per hook.
    testTimeout: 5_000,
    hookTimeout: 10_000
  }
}
