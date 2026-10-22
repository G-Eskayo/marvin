import { describe, it, expect } from 'vitest'
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, readdirSync, lstatSync, readFileSync } from 'fs'
import { execFileSync } from 'child_process'
import os from 'os'
import path from 'path'
import { realHome, makeTestHome, removeTestHome, assertTempHome } from './support/temp_home.js'
import { ERROR_LOG } from '../electron/main/error_log.js'
import { TIMING_LOG } from '../electron/main/timing.js'
import { durationsPath, inflightPath } from '../webhook-server/merge_progress.js'

// Pipeline review 2026-10-21, F10: tests wrote 147 fake "mr:approve failed" lines into the real errors.jsonl.
describe('tests run against a temp HOME, never the real ~/.claude', () => {
  it('HOME is not the real home, in this worker and in child processes', () => {
    expect(path.resolve(os.homedir())).not.toBe(path.resolve(realHome()))
    expect(path.basename(os.homedir())).toMatch(/^marvin-test-home-/)
    expect(execFileSync('/bin/sh', ['-c', 'printf %s "$HOME"']).toString()).toBe(os.homedir())
    expect(() => assertTempHome()).not.toThrow()
  })

  it('the log paths modules fix at import time point into the temp HOME', () => {
    for (const p of [ERROR_LOG, TIMING_LOG, durationsPath(), inflightPath()]) {
      expect(p.startsWith(path.join(os.homedir(), '.claude') + path.sep)).toBe(true)
      expect(p.startsWith(path.join(realHome(), '.claude'))).toBe(false)
    }
  })

  it('the temp .claude is a real, separate folder; the rest of the home is still reachable', () => {
    const claude = path.join(os.homedir(), '.claude')
    expect(lstatSync(claude).isSymbolicLink()).toBe(false)
    if (existsSync(path.join(realHome(), '.agents'))) expect(lstatSync(path.join(os.homedir(), '.agents')).isSymbolicLink()).toBe(true)
  })

  it('assertTempHome fails closed when HOME is the real home or missing', () => {
    const saved = process.env.HOME
    try {
      process.env.HOME = realHome()
      expect(() => assertTempHome()).toThrow(/temp HOME/)
      delete process.env.HOME
      expect(() => assertTempHome()).toThrow(/temp HOME/)
    } finally {
      process.env.HOME = saved
    }
  })
})

describe('makeTestHome / removeTestHome', () => {
  const fakeReal = () => {
    const real = mkdtempSync(path.join(os.tmpdir(), 'fake-real-home-'))
    mkdirSync(path.join(real, '.claude', 'logs'), { recursive: true })
    writeFileSync(path.join(real, '.claude', 'logs', 'errors.jsonl'), 'real\n')
    writeFileSync(path.join(real, '.claude.json'), '{}')
    mkdirSync(path.join(real, '.agents', 'lib'), { recursive: true })
    writeFileSync(path.join(real, '.agents', 'lib', 'x.py'), 'keep')
    return real
  }

  it('mirrors everything except .claude*, which starts empty and writes stay in the copy', () => {
    const real = fakeReal()
    const home = makeTestHome(real)
    expect(readdirSync(home).sort()).toEqual(['.agents', '.claude'])
    expect(readdirSync(path.join(home, '.claude'))).toEqual([])
    writeFileSync(path.join(home, '.claude', 'errors.jsonl'), 'test\n')
    expect(readFileSync(path.join(real, '.claude', 'logs', 'errors.jsonl'), 'utf8')).toBe('real\n')
    removeTestHome(home)
  })

  it('removing the temp home never deletes what its links point to', () => {
    const real = fakeReal()
    const home = makeTestHome(real)
    removeTestHome(home)
    expect(existsSync(home)).toBe(false)
    expect(readFileSync(path.join(real, '.agents', 'lib', 'x.py'), 'utf8')).toBe('keep')
    expect(existsSync(path.join(real, '.claude', 'logs', 'errors.jsonl'))).toBe(true)
  })

  it('refuses to remove anything that is not a temp test home', () => {
    const real = fakeReal()
    expect(() => removeTestHome(real)).toThrow(/not a temp test home/)
    expect(existsSync(path.join(real, '.claude', 'logs', 'errors.jsonl'))).toBe(true)
    const outside = mkdtempSync(path.join(real, 'marvin-test-home-')) // right name, wrong place
    expect(() => removeTestHome(outside)).toThrow(/not a temp test home/)
  })
})
