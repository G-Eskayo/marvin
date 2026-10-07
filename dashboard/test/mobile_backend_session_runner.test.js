import { describe, it, expect } from 'vitest'
import { parseStreamLine, runSession } from '../mobile-backend/session_runner.js'

describe('session_runner', () => {
  describe('parseStreamLine', () => {
    it('returns null for empty line', () => {
      expect(parseStreamLine('')).toBeNull()
      expect(parseStreamLine('   ')).toBeNull()
    })

    it('returns null for non-JSON line', () => {
      expect(parseStreamLine('hello world')).toBeNull()
      expect(parseStreamLine('[not valid json')).toBeNull()
    })

    it('parses session_start event', () => {
      const line = JSON.stringify({ type: 'session_start', session_id: 'sess-123' })
      const result = parseStreamLine(line)
      expect(result).toEqual({ type: 'session_start', sessionId: 'sess-123' })
    })

    it('parses text_delta event', () => {
      const line = JSON.stringify({ type: 'text_delta', delta: 'Hello ' })
      const result = parseStreamLine(line)
      expect(result).toEqual({ type: 'text_delta', text: 'Hello ' })
    })

    it('parses assistant message with text block', () => {
      const line = JSON.stringify({
        type: 'assistant',
        message: {
          content: [{ type: 'text', text: 'This is the response' }]
        }
      })
      const result = parseStreamLine(line)
      expect(Array.isArray(result)).toBe(true)
      expect(result[0]).toEqual({ type: 'text_delta', text: 'This is the response' })
    })

    it('parses assistant message with tool_use block', () => {
      const line = JSON.stringify({
        type: 'assistant',
        message: {
          content: [
            {
              type: 'tool_use',
              name: 'Read',
              id: 'tool-1',
              input: { file_path: '/test.txt' }
            }
          ]
        }
      })
      const result = parseStreamLine(line)
      expect(Array.isArray(result)).toBe(true)
      expect(result[0]).toEqual({
        type: 'tool_use',
        toolName: 'Read',
        toolId: 'tool-1',
        toolInput: { file_path: '/test.txt' }
      })
    })

    it('parses result event with usage', () => {
      const line = JSON.stringify({
        type: 'result',
        result: 'Final response text',
        is_error: false,
        num_turns: 5,
        duration_ms: 1234,
        total_cost_usd: 0.01,
        usage: {
          input_tokens: 100,
          output_tokens: 50,
          cache_creation_input_tokens: 10,
          cache_read_input_tokens: 5
        }
      })
      const result = parseStreamLine(line)
      expect(result).toEqual({
        type: 'result',
        isError: false,
        resultText: 'Final response text',
        numTurns: 5,
        durationMs: 1234,
        costUsd: 0.01,
        inputTokens: 100,
        outputTokens: 50,
        cacheCreationTokens: 10,
        cacheReadTokens: 5
      })
    })

    it('parses error event', () => {
      const line = JSON.stringify({ type: 'error', message: 'Something went wrong' })
      const result = parseStreamLine(line)
      expect(result).toEqual({ type: 'error', message: 'Something went wrong' })
    })

    it('returns null for unknown event type', () => {
      const line = JSON.stringify({ type: 'unknown_type', data: 'test' })
      expect(parseStreamLine(line)).toBeNull()
    })

    it('handles missing fields gracefully', () => {
      const line = JSON.stringify({ type: 'session_start' })
      const result = parseStreamLine(line)
      expect(result).toEqual({ type: 'session_start', sessionId: undefined })
    })
  })

  describe('runSession', () => {
    // Helper to create a mock process that emits lines then closes
    function createMockProc(lines, exitCode = 0) {
      const procHandlers = {}

      const proc = {
        stdout: {}, // Will be passed to createInterface mock
        on: (event, handler) => {
          if (!procHandlers[event]) procHandlers[event] = []
          procHandlers[event].push(handler)
        }
      }

      // Store reference to trigger exit
      proc._procHandlers = procHandlers
      proc._lines = lines
      proc._exitCode = exitCode

      return proc
    }

    // Helper to create mock createInterface function
    function createMockCreateInterface(proc) {
      return ({ input }) => {
        const lineHandlers = []
        const closeHandlers = []
        const errorHandlers = []

        const mockReadline = {
          on: (event, handler) => {
            if (event === 'line') lineHandlers.push(handler)
            else if (event === 'close') closeHandlers.push(handler)
            else if (event === 'error') errorHandlers.push(handler)
          },
          close: () => {
            setTimeout(() => {
              closeHandlers.forEach((h) => h())
              if (proc._procHandlers.exit) {
                proc._procHandlers.exit.forEach((h) => h(proc._exitCode))
              }
            }, 0)
          }
        }

        // Simulate process execution
        setTimeout(() => {
          proc._lines.forEach((line) => {
            lineHandlers.forEach((h) => h(line))
          })
          mockReadline.close()
        }, 0)

        return mockReadline
      }
    }

    it('parses events from stream', async () => {
      const lines = [
        JSON.stringify({ type: 'session_start', session_id: 'sess-456' }),
        JSON.stringify({ type: 'text_delta', delta: 'Hello' }),
        JSON.stringify({
          type: 'result',
          result: 'Hello world',
          is_error: false,
          num_turns: 1,
          duration_ms: 100,
          total_cost_usd: 0.001,
          usage: { input_tokens: 10, output_tokens: 20 }
        })
      ]

      const proc = createMockProc(lines)
      const mockSpawn = () => proc
      const mockCreateInterface = createMockCreateInterface(proc)

      const result = await runSession({
        message: 'test',
        claudeBin: '/usr/local/bin/claude',
        spawnFn: mockSpawn,
        createInterfaceFn: mockCreateInterface
      })

      expect(result).toBeDefined()
      expect(result.events).toBeDefined()
      expect(result.sessionId).toBe('sess-456')
    })

    it('includes --resume flag when sessionId is provided', async () => {
      let capturedArgs = null

      const proc = createMockProc([JSON.stringify({ type: 'session_start', session_id: 'sess-789' })])
      const mockSpawn = (bin, args) => {
        capturedArgs = args
        return proc
      }
      const mockCreateInterface = createMockCreateInterface(proc)

      await runSession({
        message: 'test',
        sessionId: 'sess-old',
        claudeBin: '/usr/local/bin/claude',
        spawnFn: mockSpawn,
        createInterfaceFn: mockCreateInterface
      })

      expect(capturedArgs).toContain('--resume')
      expect(capturedArgs).toContain('sess-old')
    })

    it('includes correct claude invocation arguments', async () => {
      let capturedBin = null
      let capturedArgs = null

      const proc = createMockProc([])
      const mockSpawn = (bin, args) => {
        capturedBin = bin
        capturedArgs = args
        return proc
      }
      const mockCreateInterface = createMockCreateInterface(proc)

      await runSession({
        message: 'test message',
        claudeBin: '/path/to/claude',
        spawnFn: mockSpawn,
        createInterfaceFn: mockCreateInterface
      })

      expect(capturedBin).toBe('/path/to/claude')
      expect(capturedArgs).toContain('-p')
      expect(capturedArgs).toContain('test message')
      expect(capturedArgs).toContain('--output-format')
      expect(capturedArgs).toContain('stream-json')
      expect(capturedArgs).toContain('--verbose')
      expect(capturedArgs).toContain('--include-partial-messages')
      expect(capturedArgs).toContain('--permission-prompts')
      expect(capturedArgs).toContain('none')
    })

    it('throws if spawn fails', async () => {
      const mockSpawn = () => {
        throw new Error('spawn failed')
      }

      await expect(
        runSession({
          message: 'test',
          claudeBin: '/usr/local/bin/claude',
          spawnFn: mockSpawn
        })
      ).rejects.toThrow('spawn failed')
    })

    it('updates session ID from stream event', async () => {
      const lines = [JSON.stringify({ type: 'session_start', session_id: 'sess-new' })]

      const proc = createMockProc(lines)
      const mockSpawn = () => proc
      const mockCreateInterface = createMockCreateInterface(proc)

      const result = await runSession({
        message: 'test',
        sessionId: null,
        claudeBin: '/usr/local/bin/claude',
        spawnFn: mockSpawn,
        createInterfaceFn: mockCreateInterface
      })

      expect(result.sessionId).toBe('sess-new')
    })
  })
})
