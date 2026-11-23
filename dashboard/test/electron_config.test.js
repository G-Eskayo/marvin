import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dir = dirname(fileURLToPath(import.meta.url))
const electronMainDir = join(__dir, '../electron/main')
const webhookServerDir = join(__dir, '../webhook-server')
const mobileBackendDir = join(__dir, '../mobile-backend')

function walkDir(dir, fileList = []) {
  try {
    const files = readdirSync(dir)
    for (const file of files) {
      const path = join(dir, file)
      try {
        const stat = statSync(path)
        if (stat.isDirectory()) {
          walkDir(path, fileList)
        } else if (/\.(js|mjs|cjs|ts)$/.test(file)) {
          fileList.push(path)
        }
      } catch {
        // Skip if we can't read this entry
      }
    }
  } catch (error) {
    throw new Error(`Failed to read directory ${dir}: ${error.message}`)
  }
  return fileList
}

describe('Electron main window configuration', () => {
  it('index.js createWindow sets sandbox: true in webPreferences', () => {
    const content = readFileSync(join(electronMainDir, 'index.js'), 'utf-8')
    // Match the createWindow function's webPreferences block and ensure sandbox: true
    const createWindowMatch = content.match(/createWindow\s*\([^)]*\)\s*\{[\s\S]*?webPreferences:\s*\{[\s\S]*?sandbox:\s*true/m)
    expect(createWindowMatch, 'index.js createWindow must have sandbox: true in webPreferences').toBeTruthy()
    // Ensure it's not sandbox: false
    expect(content).not.toMatch(/function createWindow[\s\S]*?sandbox:\s*false/)
  })
})

describe('Shared code isolation from Electron', () => {
  it('webhook-server and mobile-backend do not import from electron', () => {
    const webhookFiles = walkDir(webhookServerDir)
    const mobileFiles = walkDir(mobileBackendDir)

    expect(webhookFiles.length, 'webhook-server should have source files').toBeGreaterThan(0)
    expect(mobileFiles.length, 'mobile-backend should have source files').toBeGreaterThan(0)

    const allFiles = [...webhookFiles, ...mobileFiles]

    const electronImports = []
    for (const path of allFiles) {
      try {
        const content = readFileSync(path, 'utf-8')
        // Check for various import patterns:
        // - import ... from 'electron' or "electron"
        // - import ... from 'electron/main' (or any subpath)
        // - import('electron') (dynamic)
        // - require('electron') or require("electron")
        const hasElectronImport = /(?:^|\n)\s*import\s+(?:{[^}]*}|\w+|[^;]*)\s+from\s+['"]electron(?:\/[^'"]*)?['"]|import\s*\(\s*['"]electron(?:\/[^'"]*)['"]|require\s*\(\s*['"]electron(?:\/[^'"]*)['"][^)]*\)/m.test(content)
        if (hasElectronImport) {
          electronImports.push(path)
        }
      } catch {
        // Skip files we can't read
      }
    }

    expect(electronImports, 'webhook-server and mobile-backend should not import electron').toEqual([])
  })
})
