import { spawn } from 'child_process'
import { existsSync } from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
export const TEST_SLOT_SCRIPT = path.resolve(__dirname, '..', '..', 'lib', 'test_slot.py')
const VENV_PYTHON = path.resolve(__dirname, '..', '..', 'venv', 'bin', 'python')
// A worktree or a gate copy has no venv of its own; test_slot.py needs only the standard library.
const PYTHON = existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3'

// marvin#940: hold this machine's one test slot (lib/test_slot.py) from Node, which has no flock: a small holder
// process takes it and keeps it until we close its stdin (or this process dies, which closes it too). Resolves
// { held, release } once held. Inside a held slot (MARVIN_TEST_SLOT set), or when the holder can't start, nothing is
// waited for: a broken holder must never stop a merge.
// unref: the holder never keeps this process alive (vitest.config.js); it ends with us, its stdin closing.
export function holdTestSlot(args, { spawnFn = spawn, python = PYTHON, script = TEST_SLOT_SCRIPT, unref = false } = {}) {
  const none = { held: false, release: async () => {} }
  if (process.env.MARVIN_TEST_SLOT) return Promise.resolve(none)
  return new Promise((resolve) => {
    let child
    try {
      child = spawnFn(python, [script, ...args], { stdio: ['pipe', 'pipe', 'inherit'] })
    } catch { resolve(none); return }
    let settled = false
    const exited = new Promise((r) => { child.once('exit', r); child.once('error', r) })
    const settle = (v) => { if (!settled) { settled = true; resolve(v) } }
    child.once('error', () => settle(none))
    child.once('exit', () => settle(none))
    let out = ''
    child.stdout.on('data', (b) => {
      out += b
      if (out.includes('held\n')) {
        if (unref) { child.unref(); child.stdin.unref?.(); child.stdout.unref?.() }
        settle({ held: true, release: async () => { try { child.stdin.end() } catch { /* gone already */ } await exited } })
      }
    })
  })
}

// A whole run (no file or name filter) is heavy and takes the slot; `vitest run test/x.test.js` is small and never waits.
export function vitestIsHeavy(argv = process.argv) {
  const i = argv.findIndex((a) => /(^|\/)vitest(\.m?js)?$/.test(a))
  return !argv.slice(i + 1).some((a) => !a.startsWith('-') && a !== 'run' && a !== 'watch')
}

// marvin#940, from vitest.config.js in the main process before any worker starts. A whole run waits for this machine's
// slot (behind a merge or another run) and holds it until vitest exits. Either way MARVIN_TEST_SLOT is set, so workers,
// the tests and anything they start pass straight through instead of queueing on the real slot.
export async function takeSlotForVitest(argv = process.argv, { hold = holdTestSlot, python } = {}) {
  if (process.env.MARVIN_TEST_SLOT) return
  if (vitestIsHeavy(argv)) {
    await hold(['hold', '--what', 'vitest (dashboard)'], { unref: true, ...(python ? { python } : {}) })
    process.env.MARVIN_TEST_SLOT = 'vitest (dashboard)'
  } else {
    process.env.MARVIN_TEST_SLOT = 'vitest (small run, not queued)'
  }
}
