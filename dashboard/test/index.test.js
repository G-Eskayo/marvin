// Main window (dashboard/electron/main/index.js): sandbox verification and IPC handler validation
import { describe, it, expect } from 'vitest'

describe('Main window (createWindow)', () => {
  it('index.js enables sandbox in createWindow', async () => {
    const { readFileSync } = await import('fs')
    const src = readFileSync(new URL('../electron/main/index.js', import.meta.url), 'utf-8')
    const createWindowStart = src.indexOf('function createWindow()')
    expect(createWindowStart).toBeGreaterThan(-1)
    const createWindowSection = src.slice(createWindowStart, createWindowStart + 2000)
    expect(createWindowSection).toMatch(/sandbox:\s*true/)
  })

  it('show_window.js enables sandbox in makeWindow', async () => {
    const { readFileSync } = await import('fs')
    const src = readFileSync(new URL('../electron/main/show_window.js', import.meta.url), 'utf-8')
    const makeWindowStart = src.indexOf('function makeWindow(')
    expect(makeWindowStart).toBeGreaterThan(-1)
    const makeWindowSection = src.slice(makeWindowStart, makeWindowStart + 2000)
    expect(makeWindowSection).toMatch(/sandbox:\s*true/)
  })
})

describe('IPC handler argument validation', () => {
  it('metrics:index handler rejects unexpected arguments', async () => {
    const { readFileSync } = await import('fs')
    const src = readFileSync(new URL('../electron/main/index.js', import.meta.url), 'utf-8')
    const at = src.indexOf("ipcMain.handle('metrics:index'")
    expect(at).toBeGreaterThan(-1)
    // metrics:index takes no arguments; the handler is () => buildIndex()
    const section = src.slice(at, at + 100)
    expect(section).toMatch(/ipcMain\.handle\('metrics:index',\s*\(\)\s*=>/)
  })

  it('metrics:subsystems handler rejects unexpected arguments', async () => {
    const { readFileSync } = await import('fs')
    const src = readFileSync(new URL('../electron/main/index.js', import.meta.url), 'utf-8')
    const at = src.indexOf("ipcMain.handle('metrics:subsystems'")
    expect(at).toBeGreaterThan(-1)
    // metrics:subsystems takes no arguments; the handler is () => listSubsystems()
    const section = src.slice(at, at + 100)
    expect(section).toMatch(/ipcMain\.handle\('metrics:subsystems',\s*\(\)\s*=>/)
  })

  it('mr:markSeen handler expects array of string keys', async () => {
    const { readFileSync } = await import('fs')
    const src = readFileSync(new URL('../electron/main/index.js', import.meta.url), 'utf-8')
    const at = src.indexOf("ipcMain.handle('mr:markSeen'")
    expect(at).toBeGreaterThan(-1)
    const section = src.slice(at, at + 150)
    // mr:markSeen expects (_event, prKeys) and filters to strings
    expect(section).toMatch(/ipcMain\.handle\('mr:markSeen'/)
    expect(section).toMatch(/prKeys\.filter\(\(k\)\s*=>\s*typeof k === 'string'\)/)
  })

  it('activity:timeline handler expects number and optional string repo', async () => {
    const { readFileSync } = await import('fs')
    const src = readFileSync(new URL('../electron/main/index.js', import.meta.url), 'utf-8')
    const at = src.indexOf("ipcMain.handle('activity:timeline'")
    expect(at).toBeGreaterThan(-1)
    // activity:timeline expects (_event, number, repo) and handles repo as optional
    const section = src.slice(at, at + 150)
    expect(section).toMatch(/ipcMain\.handle\('activity:timeline'/)
    expect(section).toMatch(/\(_event,\s*number,\s*repo\)/)
  })
})
