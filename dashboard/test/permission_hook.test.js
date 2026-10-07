import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createReadStream, writeFileSync, mkdtempSync, rmSync } from 'fs'
import { join } from 'path'
import { tmpdir } from 'os'
import { spawn } from 'child_process'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

describe('permission_hook', () => {
  let testDir
  let filePath
  const hookPath = join(__dirname, '..', 'mobile-backend', 'permission_hook.js')

  beforeEach(() => {
    testDir = mkdtempSync(join(tmpdir(), 'permission-hook-test-'))
    filePath = join(testDir, 'pending-actions.json')
    writeFileSync(filePath, JSON.stringify({ actions: [] }))
  })

  afterEach(() => {
    rmSync(testDir, { recursive: true })
  })

  async function runHook(inputPayload) {
    return new Promise((resolve, reject) => {
      const child = spawn('node', [hookPath], {
        env: {
          ...process.env,
          PENDING_ACTION_PATH: filePath,
          HOOK_TIMEOUT_MS: '500'
        },
        stdio: ['pipe', 'pipe', 'pipe']
      })

      let output = ''
      let errorOutput = ''

      child.stdout.on('data', (data) => {
        output += data.toString()
      })

      child.stderr.on('data', (data) => {
        errorOutput += data.toString()
      })

      child.on('exit', (code) => {
        if (code !== 0) {
          reject(new Error(`Hook exited with code ${code}: ${errorOutput}`))
        } else {
          try {
            const result = JSON.parse(output.trim())
            resolve(result)
          } catch (err) {
            reject(new Error(`Failed to parse hook output: ${output}`))
          }
        }
      })

      child.stdin.write(JSON.stringify(inputPayload))
      child.stdin.end()
    })
  }

  describe('read-only tools', () => {
    it('allows Read tool immediately', async () => {
      const result = await runHook({
        tool_name: 'Read',
        tool_input: { file_path: '/test.txt' },
        session_id: 'sess-123'
      })

      expect(result.permissionDecision).toBe('allow')
    })

    it('allows Grep tool immediately', async () => {
      const result = await runHook({
        tool_name: 'Grep',
        tool_input: { pattern: 'test' },
        session_id: 'sess-123'
      })

      expect(result.permissionDecision).toBe('allow')
    })

    it('allows Glob tool immediately', async () => {
      const result = await runHook({
        tool_name: 'Glob',
        tool_input: { pattern: '*.js' },
        session_id: 'sess-123'
      })

      expect(result.permissionDecision).toBe('allow')
    })

    it('allows WebSearch tool immediately', async () => {
      const result = await runHook({
        tool_name: 'WebSearch',
        tool_input: { query: 'test' },
        session_id: 'sess-123'
      })

      expect(result.permissionDecision).toBe('allow')
    })

    it('allows WebFetch tool immediately', async () => {
      const result = await runHook({
        tool_name: 'WebFetch',
        tool_input: { url: 'https://example.com' },
        session_id: 'sess-123'
      })

      expect(result.permissionDecision).toBe('allow')
    })
  })

  describe('side-effecting tools', () => {
    it('creates pending action for Bash tool', async () => {
      const result = await runHook({
        tool_name: 'Bash',
        tool_input: { command: 'npm test' },
        session_id: 'sess-123'
      })

      expect(result.permissionDecision).toBe('deny')
      expect(result.reason).toContain('Timeout')
    })

    it('creates pending action for Edit tool', async () => {
      const result = await runHook({
        tool_name: 'Edit',
        tool_input: { file_path: 'src/index.js' },
        session_id: 'sess-456'
      })

      expect(result.permissionDecision).toBe('deny')
      expect(result.reason).toContain('Timeout')
    })

    it('creates pending action for Write tool', async () => {
      const result = await runHook({
        tool_name: 'Write',
        tool_input: { file_path: 'new-file.txt' },
        session_id: 'sess-789'
      })

      expect(result.permissionDecision).toBe('deny')
      expect(result.reason).toContain('Timeout')
    })

    it('includes tool summary in pending action', async () => {
      const storeFile = join(testDir, 'verify-summary.json')
      writeFileSync(storeFile, JSON.stringify({ actions: [] }))

      const child = spawn('node', [hookPath], {
        env: {
          ...process.env,
          PENDING_ACTION_PATH: storeFile,
          HOOK_TIMEOUT_MS: '200'
        },
        stdio: ['pipe', 'pipe', 'pipe']
      })

      const payload = {
        tool_name: 'Bash',
        tool_input: { command: 'rm -rf /' },
        session_id: 'sess-check'
      }

      await new Promise((resolve) => {
        child.on('exit', resolve)
        child.stdin.write(JSON.stringify(payload))
        child.stdin.end()
      })

      const data = JSON.parse(require('fs').readFileSync(storeFile, 'utf-8'))
      expect(data.actions).toHaveLength(1)
      expect(data.actions[0].summary).toContain('Run shell command')
      expect(data.actions[0].toolName).toBe('Bash')
      expect(data.actions[0].toolInput.command).toBe('rm -rf /')
    })
  })

  describe('error handling', () => {
    it('denies on missing tool_name', async () => {
      const result = await runHook({
        tool_input: { command: 'test' },
        session_id: 'sess-123'
      })

      expect(result.permissionDecision).toBe('deny')
      expect(result.reason).toContain('Missing tool_name')
    })

    it('denies on invalid JSON input', async () => {
      return new Promise((resolve) => {
        const child = spawn('node', [hookPath], {
          env: {
            ...process.env,
            PENDING_ACTION_PATH: filePath
          },
          stdio: ['pipe', 'pipe', 'pipe']
        })

        let output = ''
        child.stdout.on('data', (data) => {
          output += data.toString()
        })

        child.on('exit', () => {
          const result = JSON.parse(output.trim())
          expect(result.permissionDecision).toBe('deny')
          expect(result.reason).toContain('Hook error')
          resolve()
        })

        child.stdin.write('not json')
        child.stdin.end()
      })
    })
  })
})
