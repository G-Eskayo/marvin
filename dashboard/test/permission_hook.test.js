import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { createServer } from 'http'
import { shouldAutoAllow, handleHook, makeRelayRequest } from '../mobile-backend/permission_hook.js'

describe('permission_hook', () => {
  describe('shouldAutoAllow', () => {
    it('auto-allows read-only tools', () => {
      expect(shouldAutoAllow('Read')).toBe(true)
      expect(shouldAutoAllow('Grep')).toBe(true)
      expect(shouldAutoAllow('Glob')).toBe(true)
      expect(shouldAutoAllow('WebSearch')).toBe(true)
    })

    it('does not auto-allow side-effecting tools', () => {
      expect(shouldAutoAllow('Bash')).toBe(false)
      expect(shouldAutoAllow('Edit')).toBe(false)
      expect(shouldAutoAllow('Write')).toBe(false)
    })
  })

  describe('handleHook', () => {
    it('auto-allows read-only tools', async () => {
      const input = { tool_name: 'Read', tool_input: { file_path: 'test.js' } }
      const result = await handleHook(input)

      expect(result.hookSpecificOutput.hookEventName).toBe('PreToolUse')
      expect(result.hookSpecificOutput.permissionDecision).toBe('allow')
      expect(result.hookSpecificOutput.permissionDecisionReason).toBe('read-only tool')
    })

    it('attempts relay contact for side-effecting tools and fails closed', async () => {
      // Without mocking makeRelayRequest, the actual HTTP call will fail
      // which is the correct fail-closed behavior
      const input = { tool_name: 'Bash', tool_input: { command: 'echo test' } }
      const result = await handleHook(input)

      // Should fail closed when relay is unreachable
      expect(result.hookSpecificOutput.permissionDecision).toBe('deny')
      expect(result.hookSpecificOutput.permissionDecisionReason).toContain('relay error')
    })

    it('returns proper structure for side-effecting tools', async () => {
      const input = { tool_name: 'Edit', tool_input: { file_path: 'test.js' } }
      const result = await handleHook(input)

      expect(result).toHaveProperty('hookSpecificOutput.hookEventName', 'PreToolUse')
      expect(result).toHaveProperty('hookSpecificOutput.permissionDecision')
      expect(result).toHaveProperty('hookSpecificOutput.permissionDecisionReason')
      expect(['allow', 'deny']).toContain(result.hookSpecificOutput.permissionDecision)
    })
  })

  describe('makeRelayRequest', () => {
    it('makes a POST request to the relay', async () => {
      const server = createServer((req, res) => {
        expect(req.method).toBe('POST')
        expect(req.url).toBe('/test')

        let body = ''
        req.on('data', (chunk) => {
          body += chunk
        })
        req.on('end', () => {
          const data = JSON.parse(body)
          expect(data.test).toBe('value')

          res.writeHead(200, { 'Content-Type': 'application/json' })
          res.end(JSON.stringify({ success: true }))
        })
      })

      await new Promise((resolve) => {
        server.listen(0, '127.0.0.1', () => {
          const port = server.address().port
          process.env.PERMISSION_RELAY_PORT = port
          resolve()
        })
      })

      try {
        const result = await makeRelayRequest('POST', '/test', { test: 'value' })
        expect(result.success).toBe(true)
      } finally {
        server.close()
      }
    })

    it('times out if relay does not respond', async () => {
      const server = createServer((req, res) => {
        // Never respond
      })

      await new Promise((resolve) => {
        server.listen(0, '127.0.0.1', () => {
          const port = server.address().port
          process.env.PERMISSION_RELAY_PORT = port
          resolve()
        })
      })

      try {
        const promise = makeRelayRequest('POST', '/test', {}, 50)
        await expect(promise).rejects.toThrow()
      } finally {
        server.close()
      }
    })

    it('fails if relay is not reachable', async () => {
      process.env.PERMISSION_RELAY_PORT = '0' // Port 0 is never listening

      const promise = makeRelayRequest('POST', '/test', {}, 50)
      await expect(promise).rejects.toThrow()
    })
  })
})
