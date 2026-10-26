import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { logStage } from '../mobile-backend/voice_latency.js'
import { readFileSync, unlinkSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'

describe('voice_latency', () => {
  let testLogPath

  beforeEach(() => {
    testLogPath = path.join(tmpdir(), `voice-latency-${Date.now()}.jsonl`)
  })

  afterEach(() => {
    try {
      unlinkSync(testLogPath)
    } catch {}
  })

  it('logs a stage with timestamp', async () => {
    const turnId = 'turn-123'
    const stage = 'received'
    const tsMs = 1000

    await logStage(turnId, stage, tsMs, { path: testLogPath })

    const content = readFileSync(testLogPath, 'utf-8').trim()
    const line = JSON.parse(content)

    expect(line).toEqual(
      expect.objectContaining({
        turnId: 'turn-123',
        stage: 'received',
        tsMs: 1000
      })
    )
  })

  it('appends multiple lines', async () => {
    await logStage('turn-1', 'received', 1000, { path: testLogPath })
    await logStage('turn-1', 'routed', 1100, { path: testLogPath })

    const content = readFileSync(testLogPath, 'utf-8').trim().split('\n')
    expect(content.length).toBe(2)
    expect(JSON.parse(content[0]).stage).toBe('received')
    expect(JSON.parse(content[1]).stage).toBe('routed')
  })

  it('uses default path when not provided', async () => {
    // Override HOME to a temp directory so the default path goes to tmpdir
    const tempHome = path.join(tmpdir(), `home-${Date.now()}`)
    const originalHome = process.env.HOME
    try {
      process.env.HOME = tempHome

      // Call without path option to test default path behavior
      await logStage('turn-123', 'received', 1000, {})

      // The default path is ~/.claude/logs/voice-latency.jsonl
      const defaultPath = path.join(tempHome, '.claude', 'logs', 'voice-latency.jsonl')
      const content = readFileSync(defaultPath, 'utf-8').trim()
      const line = JSON.parse(content)
      expect(line).toEqual(
        expect.objectContaining({
          turnId: 'turn-123',
          stage: 'received'
        })
      )
    } finally {
      process.env.HOME = originalHome
      // Clean up temp files
      try {
        const defaultPath = path.join(tempHome, '.claude', 'logs', 'voice-latency.jsonl')
        unlinkSync(defaultPath)
      } catch {}
    }
  })

  it('logs common stages', async () => {
    const stages = ['received', 'routed', 'first_token', 'first_sentence']

    for (const stage of stages) {
      await logStage(`turn-${stage}`, stage, 1000, { path: testLogPath })
    }

    const content = readFileSync(testLogPath, 'utf-8').trim().split('\n')
    expect(content.length).toBe(stages.length)
  })

  it('preserves timestamp precision', async () => {
    const tsMs = 1234567890.123

    await logStage('turn-1', 'test', tsMs, { path: testLogPath })

    const content = readFileSync(testLogPath, 'utf-8').trim()
    const line = JSON.parse(content)

    expect(line.tsMs).toBe(tsMs)
  })
})
