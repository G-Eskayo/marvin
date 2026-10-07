import { describe, it, expect, beforeEach } from 'vitest'
import { readFileSync } from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { normaliseEvent, runSession } from '../mobile-backend/session_runner.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FIXTURES_DIR = path.join(__dirname, 'fixtures')

// Read fixture file and return array of lines
function loadFixture(name) {
  const filePath = path.join(FIXTURES_DIR, name)
  const content = readFileSync(filePath, 'utf-8')
  return content.trim().split('\n')
}

// Mock child process that reads from fixture lines
function createMockChildProcess(fixtureLines) {
  const { PassThrough } = require('stream')

  const stdout = new PassThrough()
  let exitCallback = null
  let didExit = false

  // Start writing lines immediately after a small delay
  setTimeout(() => {
    fixtureLines.forEach((line, index) => {
      setTimeout(() => {
        if (!didExit) {
          stdout.write(line + '\n')
        }
      }, index * 10)
    })

    // End the stream after all lines are written
    setTimeout(() => {
      stdout.end()
      didExit = true
      if (exitCallback) exitCallback(0)
    }, fixtureLines.length * 10 + 10)
  }, 0)

  return {
    stdout,
    on(event, callback) {
      if (event === 'exit') {
        exitCallback = callback
      }
    }
  }
}

describe('session_runner', () => {
  describe('normaliseEvent', () => {
    it('parses system event with session_id', () => {
      const raw = '{"type":"system","session_id":"sess-123"}'
      const events = normaliseEvent(raw)
      expect(events).toEqual([{ type: 'session', sessionId: 'sess-123' }])
    })

    it('parses assistant text message', () => {
      const raw = '{"type":"assistant","message":{"content":[{"type":"text","text":"Hello"}]}}'
      const events = normaliseEvent(raw)
      expect(events).toEqual([{ type: 'text', text: 'Hello' }])
    })

    it('parses assistant tool_use block', () => {
      const raw = '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"grep","input":{"file":"test.txt"}}]}}'
      const events = normaliseEvent(raw)
      expect(events).toEqual([{ type: 'tool_use', name: 'grep', input: { file: 'test.txt' } }])
    })

    it('parses assistant with both text and tool_use', () => {
      const raw = '{"type":"assistant","message":{"content":[{"type":"text","text":"Let me check"},{"type":"tool_use","name":"grep","input":{}}]}}'
      const events = normaliseEvent(raw)
      expect(events).toEqual([
        { type: 'text', text: 'Let me check' },
        { type: 'tool_use', name: 'grep', input: {} }
      ])
    })

    it('parses result event with usage and cost', () => {
      const raw = '{"type":"result","session_id":"sess-123","result":"final text","usage":{"input_tokens":10,"output_tokens":5},"total_cost_usd":0.001,"duration_ms":100,"is_error":false}'
      const events = normaliseEvent(raw)
      expect(events).toEqual([{
        type: 'result',
        text: 'final text',
        sessionId: 'sess-123',
        costUsd: 0.001,
        durationMs: 100,
        isError: false
      }])
    })

    it('skips malformed JSON silently', () => {
      const events = normaliseEvent('not json at all')
      expect(events).toEqual([])
    })

    it('skips empty lines', () => {
      const events = normaliseEvent('')
      expect(events).toEqual([])
    })

    it('skips null', () => {
      const events = normaliseEvent(null)
      expect(events).toEqual([])
    })

    it('handles stream_event with text_delta', () => {
      const raw = '{"type":"stream_event","delta":{"type":"text_delta","text":"partial "}}'
      const events = normaliseEvent(raw)
      expect(events).toEqual([{ type: 'text', text: 'partial ' }])
    })
  })

  describe('runSession', () => {
    it('yields events from plain-reply fixture', async () => {
      const fixtureLines = loadFixture('plain-reply.ndjson')
      const mockSpawn = () => createMockChildProcess(fixtureLines)

      const events = []
      for await (const event of runSession({ message: 'hello', spawnFn: mockSpawn })) {
        events.push(event)
      }

      expect(events).toEqual([
        { type: 'session', sessionId: 'session-plain-001' },
        { type: 'text', text: 'Hello there! This is a simple text response.' },
        { type: 'result', text: 'Hello there! This is a simple text response.', sessionId: 'session-plain-001', costUsd: 0.0015, durationMs: 456, isError: false }
      ])
    })

    it('yields events from tool-use-attempt fixture', async () => {
      const fixtureLines = loadFixture('tool-use-attempt.ndjson')
      const mockSpawn = () => createMockChildProcess(fixtureLines)

      const events = []
      for await (const event of runSession({ message: 'check something', spawnFn: mockSpawn })) {
        events.push(event)
      }

      expect(events).toHaveLength(4)
      expect(events[0]).toEqual({ type: 'session', sessionId: 'session-tool-001' })
      expect(events[1]).toEqual({ type: 'text', text: 'Let me check that for you.' })
      expect(events[2]).toEqual({ type: 'tool_use', name: 'grep', input: { pattern: 'example', file: 'test.txt' } })
      expect(events[3].type).toBe('result')
    })

    it('includes --resume flag when sessionId is provided', async () => {
      let capturedArgs = null
      const mockSpawn = (bin, args) => {
        capturedArgs = args
        return createMockChildProcess(loadFixture('resume.ndjson'))
      }

      for await (const _ of runSession({ message: 'continue', sessionId: 'session-resume-001', spawnFn: mockSpawn })) {
        // consume events
      }

      expect(capturedArgs).toContain('--resume')
      expect(capturedArgs).toContain('session-resume-001')
    })

    it('includes --settings flag with hook config path', async () => {
      let capturedArgs = null
      const mockSpawn = (bin, args) => {
        capturedArgs = args
        return createMockChildProcess(loadFixture('plain-reply.ndjson'))
      }

      for await (const _ of runSession({ message: 'test', spawnFn: mockSpawn })) {
        // consume events
      }

      const settingsIndex = capturedArgs.indexOf('--settings')
      expect(settingsIndex).toBeGreaterThanOrEqual(0)
      expect(capturedArgs[settingsIndex + 1]).toBeDefined()
      expect(capturedArgs[settingsIndex + 1]).toMatch(/mobile-backend-permission-settings\.json/)
    })

    it('surfaces spawn ENOENT as error event', async () => {
      const mockSpawn = () => {
        const err = new Error('ENOENT: no such file or directory')
        err.code = 'ENOENT'
        throw err
      }

      const events = []
      for await (const event of runSession({ message: 'test', spawnFn: mockSpawn })) {
        events.push(event)
      }

      expect(events).toHaveLength(1)
      expect(events[0].type).toBe('error')
      expect(events[0].message).toContain('Failed to spawn')
    })

    it('surfaces nonzero exit code as error event', async () => {
      const { PassThrough } = require('stream')
      const stdout = new PassThrough()

      setTimeout(() => {
        stdout.end()
      }, 10)

      let exitCallback = null
      const mockChildProcess = {
        stdout,
        on(event, callback) {
          if (event === 'exit') {
            exitCallback = callback
            setTimeout(() => callback(1), 20)
          }
        }
      }

      const mockSpawn = () => mockChildProcess

      const events = []
      for await (const event of runSession({ message: 'test', spawnFn: mockSpawn })) {
        events.push(event)
      }

      expect(events).toHaveLength(1)
      expect(events[0].type).toBe('error')
      expect(events[0].message).toContain('exited with code 1')
    })
  })
})
