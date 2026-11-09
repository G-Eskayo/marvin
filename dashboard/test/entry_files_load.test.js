import { describe, it, expect } from 'vitest'
import { execFileSync } from 'child_process'
import { readdirSync } from 'fs'
import path from 'path'

// 2026-11-04: an auto-merge left webhook-server/index.js importing the same name twice. No test imported that file,
// so the gate passed it and main's merge server could not start. Every entry module must at least parse.
const ROOT = path.resolve(import.meta.dirname, '..')
const files = ['webhook-server', 'electron/main', 'electron/preload']
  .flatMap((d) => readdirSync(path.join(ROOT, d)).filter((f) => f.endsWith('.js')).map((f) => path.join(d, f)))

describe('every merge-server and Electron main file parses', () => {
  it('finds the entry files', () => {
    expect(files).toEqual(expect.arrayContaining(['webhook-server/index.js', 'electron/main/index.js', 'electron/preload/index.js']))
  })
  for (const f of files) {
    it(f, () => {
      expect(() => execFileSync(process.execPath, ['--check', path.join(ROOT, f)], { stdio: 'pipe' })).not.toThrow()
    })
  }
})
