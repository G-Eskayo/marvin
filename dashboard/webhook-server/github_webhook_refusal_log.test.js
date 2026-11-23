import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createRefusalLogger, getRefusalLogFile } from './github_webhook_refusal_log.js'
import { promises as fs } from 'fs'
import path from 'path'
import os from 'os'

describe('github_webhook_refusal_log', () => {
  let tempDir
  let logDir

  beforeEach(async () => {
    tempDir = path.join(os.tmpdir(), `webhook-refusal-test-${Date.now()}`)
    logDir = path.join(tempDir, '.claude', 'logs')
    await fs.mkdir(logDir, { recursive: true })
  })

  afterEach(async () => {
    try {
      await fs.rm(tempDir, { recursive: true })
    } catch {}
  })

  it('appends refusal lines to the log file', async () => {
    const logger = createRefusalLogger(tempDir)
    logger('{"kind":"webhook-refusal","reason":"test"}\n')
    logger('{"kind":"webhook-refusal","reason":"test2"}\n')

    const content = await fs.readFile(getRefusalLogFile(tempDir), 'utf-8')
    expect(content).toContain('webhook-refusal')
    expect(content.split('\n').filter(Boolean)).toHaveLength(2)
  })

  it('rotates log file when size exceeds limit', async () => {
    const logger = createRefusalLogger(tempDir)
    const logFile = getRefusalLogFile(tempDir)

    // Add lines until we exceed the size limit (10 MB).
    // Using large lines to trigger rotation faster.
    const largeLine = JSON.stringify({ kind: 'webhook-refusal', data: 'x'.repeat(1_000_000) }) + '\n'

    for (let i = 0; i < 15; i++) {
      logger(largeLine)
    }

    // After rotation, original file should be renamed to .0
    const stat0 = await fs.stat(path.join(logDir, 'github-webhook-refusals.jsonl.0')).catch(() => null)
    expect(stat0).not.toBeNull()
  })

  it('limits number of rotated files', async () => {
    const logger = createRefusalLogger(tempDir)
    const logDir = path.join(tempDir, '.claude', 'logs')

    // Simulate multiple rotations by creating files and rotating
    const largeLine = 'x'.repeat(100_000) + '\n'
    for (let i = 0; i < 50; i++) {
      logger(largeLine)
    }

    // Check that we don't have more than 3 rotation files (.0, .1, .2)
    const files = await fs.readdir(logDir)
    const rotationFiles = files.filter((f) => f.match(/github-webhook-refusals\.jsonl\.\d+/))
    expect(rotationFiles.length).toBeLessThanOrEqual(3)
  })

  it('handles missing home directory gracefully', async () => {
    // When home directory doesn't exist, createRefusalLogger should not throw
    const logger = createRefusalLogger('/nonexistent/path')
    expect(() => logger('test\n')).not.toThrow()
  })
})
