// MARVIN-owned state lives under ~/.agents/var (self-reliance rule, 2026-10-21). Temp HOME only.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, readFileSync, existsSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { marvinVarDir, varPath, migrateOnce } from '../electron/main/marvin_paths.js'

let home, prev, prevVar
beforeEach(() => {
  prev = process.env.HOME
  prevVar = process.env.MARVIN_VAR_DIR
  delete process.env.MARVIN_VAR_DIR
  home = mkdtempSync(path.join(tmpdir(), 'mpaths-'))
  process.env.HOME = home
})
afterEach(() => {
  process.env.HOME = prev
  if (prevVar === undefined) delete process.env.MARVIN_VAR_DIR
  else process.env.MARVIN_VAR_DIR = prevVar
  rmSync(home, { recursive: true, force: true })
})

describe('marvinVarDir', () => {
  it('is ~/.agents/var under the current HOME, never ~/.claude', () => {
    expect(marvinVarDir()).toBe(path.join(home, '.agents', 'var'))
    expect(varPath('docs-github')).not.toContain('.claude')
  })
  it('honours MARVIN_VAR_DIR', () => {
    expect(marvinVarDir({ MARVIN_VAR_DIR: '/x/y' })).toBe('/x/y')
  })
})

describe('migrateOnce', () => {
  it('moves an old folder to the new place once, with its contents', () => {
    const old = path.join(home, '.claude', 'logs', 'docs-github')
    mkdirSync(old, { recursive: true })
    writeFileSync(path.join(old, 'a.json'), '{"x":1}')
    expect(migrateOnce(old, varPath('docs-github'))).toBe(true)
    expect(readFileSync(varPath('docs-github', 'a.json'), 'utf8')).toBe('{"x":1}')
    expect(existsSync(old)).toBe(false)
    expect(migrateOnce(old, varPath('docs-github'))).toBe(false)
  })
  it('never overwrites a newer copy at the new place', () => {
    const old = path.join(home, 'old.json')
    writeFileSync(old, 'old')
    mkdirSync(path.dirname(varPath('m.json')), { recursive: true })
    writeFileSync(varPath('m.json'), 'new')
    expect(migrateOnce(old, varPath('m.json'))).toBe(false)
    expect(readFileSync(varPath('m.json'), 'utf8')).toBe('new')
    expect(existsSync(old)).toBe(true)
  })
  it('does nothing (and does not throw) when there is nothing to move', () => {
    expect(migrateOnce(path.join(home, 'nope'), varPath('x'))).toBe(false)
    expect(migrateOnce(null, varPath('x'))).toBe(false)
  })
})
