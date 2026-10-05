import { describe, it, expect } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync, utimesSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { readCatalog, readOverrides, readMasterDoc } from '../electron/main/catalog.js'
import { readRegistry } from '../electron/main/boards.js'

const withDir = (fn) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'catalog-'))
  try {
    return fn(dir)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}
const put = (dir, name, obj) => writeFileSync(path.join(dir, name), typeof obj === 'string' ? obj : JSON.stringify(obj))

describe('readCatalog', () => {
  it('reads this device\'s file', () =>
    withDir((dir) => {
      put(dir, 'projects.mac-mini.json', { projects: [{ id: 'a' }] })
      put(dir, 'projects.laptop.json', { projects: [{ id: 'b' }] })
      expect(readCatalog({ dir, deviceId: 'mac-mini' }).projects[0].id).toBe('a')
    }))

  it('falls back to the newest catalog file when the device is unknown', () =>
    withDir((dir) => {
      put(dir, 'projects.old.json', { projects: [{ id: 'old' }] })
      put(dir, 'projects.new.json', { projects: [{ id: 'new' }] })
      utimesSync(path.join(dir, 'projects.old.json'), new Date(2020, 0, 1), new Date(2020, 0, 1))
      expect(readCatalog({ dir, deviceId: null }).projects[0].id).toBe('new')
    }))

  it('returns null for a missing directory or corrupt file', () =>
    withDir((dir) => {
      expect(readCatalog({ dir: path.join(dir, 'nope'), deviceId: 'x' })).toBeNull()
      put(dir, 'projects.x.json', '{bad')
      expect(readCatalog({ dir, deviceId: 'x' })).toBeNull()
    }))
})

describe('readOverrides / readMasterDoc', () => {
  it('ignores comment keys and non-objects', () =>
    withDir((dir) => {
      put(dir, 'overrides.json', { _readme: 'x', a: { due: '2026-10-25' }, b: 3 })
      expect(readOverrides(dir)).toEqual({ a: { due: '2026-10-25' } })
      expect(readOverrides(path.join(dir, 'missing'))).toEqual({})
    }))

  it('reads the master doc or returns null', () =>
    withDir((dir) => {
      expect(readMasterDoc(path.join(dir, 'm.md'))).toBeNull()
      put(dir, 'm.md', '# hi')
      expect(readMasterDoc(path.join(dir, 'm.md'))).toBe('# hi')
    }))
})

describe('readRegistry merges shared due dates', () => {
  it('overrides supply due/dueHard for a board, keyed by project id', () =>
    withDir((dir) => {
      const reg = path.join(dir, 'registry.json')
      put(dir, 'registry.json', { boards: [{ repo: 'G-Eskayo/Clarity-Captions', name: 'clarity' }, { repo: 'G-Eskayo/marvin', name: 'marvin' }] })
      const boards = readRegistry(reg, { 'clarity-captions': { due: '2026-10-25', dueHard: true } })
      expect(boards[0]).toMatchObject({ due: '2026-10-25', dueHard: true })
      expect(boards[1].due).toBeUndefined()
    }))
})
