// Tests never touch the real ~/.claude (pipeline review 2026-10-21, F10): 147 of 160 "mr:approve failed" lines in the
// real errors.jsonl came from test/timing.test.js. The same design as the Python suite (lib/real_home_guard.py): HOME
// becomes a temp folder that mirrors the real home through symlinks, except .claude*, which starts empty. Module-level
// path constants (ERROR_LOG, TIMING_LOG, ...) and every child process then land in the temp copy.
// O(entries in the real home) symlinks, once per run.
import { mkdtempSync, readdirSync, symlinkSync, mkdirSync, lstatSync, unlinkSync, rmSync, rmdirSync, realpathSync } from 'fs'
import os from 'os'
import path from 'path'

export const realHome = () => os.userInfo().homedir // from the password database, whatever HOME says

export function makeTestHome(real = realHome(), parent = os.tmpdir()) {
  const home = mkdtempSync(path.join(parent, 'marvin-test-home-'))
  let names = []
  try { names = readdirSync(real) } catch { /* an unreadable home mirrors nothing */ }
  for (const name of names) {
    if (name.startsWith('.claude')) continue
    try { symlinkSync(path.join(real, name), path.join(home, name)) } catch { /* skip what cannot be linked */ }
  }
  mkdirSync(path.join(home, '.claude'))
  return home
}

// Removes the links themselves (never what they point to), then the temp .claude, then the folder. Refuses anything
// that is not one of our temp homes: a test once wiped the real ~/.claude/logs with a recursive remove (2026-10-09).
export function removeTestHome(home) {
  const resolved = realpathSync(home)
  if (!path.basename(resolved).startsWith('marvin-test-home-') || path.dirname(resolved) !== realpathSync(os.tmpdir())) {
    throw new Error(`refusing to remove ${home}: not a temp test home`)
  }
  for (const name of readdirSync(resolved)) {
    const p = path.join(resolved, name)
    if (lstatSync(p).isSymbolicLink()) unlinkSync(p)
  }
  rmSync(path.join(resolved, '.claude'), { recursive: true, force: true })
  rmdirSync(resolved)
}

// The fail-closed check every test file runs first (vitest.config.js setupFiles).
export function assertTempHome() {
  const real = realHome()
  if (!process.env.HOME || path.resolve(process.env.HOME) === path.resolve(real)) {
    throw new Error('tests must run with a temp HOME (dashboard/vitest.config.js); refusing to run against the real ~/.claude')
  }
}
