import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { createPermissionBridge, classifyTool, summarize } from '../mobile-backend/permission_bridge.js'

describe('permission_bridge', () => {
  describe('classifyTool', () => {
    it('classifies Read as read-only', () => {
      expect(classifyTool('Read')).toBe('read')
    })

    it('classifies Grep as read-only', () => {
      expect(classifyTool('Grep')).toBe('read')
    })

    it('classifies Glob as read-only', () => {
      expect(classifyTool('Glob')).toBe('read')
    })

    it('classifies WebSearch as read-only', () => {
      expect(classifyTool('WebSearch')).toBe('read')
    })

    it('classifies Bash as side-effecting', () => {
      expect(classifyTool('Bash')).toBe('side-effecting')
    })

    it('classifies Edit as side-effecting', () => {
      expect(classifyTool('Edit')).toBe('side-effecting')
    })

    it('classifies Write as side-effecting', () => {
      expect(classifyTool('Write')).toBe('side-effecting')
    })
  })

  describe('summarize', () => {
    it('returns tool name if no input', () => {
      expect(summarize('Bash', null)).toBe('Bash')
      expect(summarize('Edit', undefined)).toBe('Edit')
    })

    it('summarizes Bash with short command', () => {
      expect(summarize('Bash', { command: 'ls -la' })).toBe('Bash: ls -la')
    })

    it('truncates long Bash commands', () => {
      const longCmd = 'a'.repeat(100)
      const summary = summarize('Bash', { command: longCmd })
      expect(summary).toContain('…')
      expect(summary.length).toBeLessThan(100)
    })

    it('summarizes Edit with file path', () => {
      expect(summarize('Edit', { file_path: '/path/to/file.js' })).toBe('Edit: /path/to/file.js')
    })

    it('summarizes Write with file path', () => {
      expect(summarize('Write', { filePath: '/path/to/file.txt' })).toBe('Write: /path/to/file.txt')
    })

    it('summarizes WebFetch with URL', () => {
      expect(summarize('WebFetch', { url: 'https://example.com/api' })).toBe('Fetch: https://example.com/api')
    })

    it('truncates long URLs', () => {
      const longUrl = 'https://example.com/' + 'a'.repeat(100)
      const summary = summarize('WebFetch', { url: longUrl })
      expect(summary).toContain('…')
    })

    it('summarizes WebSearch with query', () => {
      expect(summarize('WebSearch', { query: 'hello world' })).toBe('Search: hello world')
    })
  })

  describe('createPermissionBridge', () => {
    let bridge

    beforeEach(() => {
      bridge = createPermissionBridge()
    })

    describe('requestPermission', () => {
      it('auto-allows read-only tools without pending', () => {
        const result = bridge.requestPermission('Read', { file_path: 'test.js' })
        expect(result.id).toBeNull()
        expect(result.behavior).toBe('allow')
        expect(result.promise).toBeUndefined()
      })

      it('creates pending for side-effecting tools', () => {
        const result = bridge.requestPermission('Bash', { command: 'rm -rf /' })
        expect(result.id).not.toBeNull()
        expect(result.behavior).toBe('pending')
        expect(result.promise).toBeDefined()
      })

      it('increments pending IDs', () => {
        const id1 = bridge.requestPermission('Bash', {}).id
        const id2 = bridge.requestPermission('Edit', {}).id
        expect(Number(id2)).toBeGreaterThan(Number(id1))
      })

      it('pending shape includes tool info', () => {
        bridge.requestPermission('Bash', { command: 'echo test' })
        const pending = bridge.list()
        expect(pending).toHaveLength(1)
        expect(pending[0]).toHaveProperty('id')
        expect(pending[0]).toHaveProperty('summary')
        expect(pending[0]).toHaveProperty('toolName', 'Bash')
      })
    })

    describe('resolve', () => {
      it('approves a pending action', async () => {
        const { id, promise } = bridge.requestPermission('Bash', { command: 'test' })
        bridge.resolve(id, true)
        const decision = await promise
        expect(decision).toBe(true)
      })

      it('denies a pending action', async () => {
        const { id, promise } = bridge.requestPermission('Edit', {})
        bridge.resolve(id, false)
        const decision = await promise
        expect(decision).toBe(false)
      })

      it('removes from list after resolve', () => {
        const { id } = bridge.requestPermission('Bash', {})
        bridge.resolve(id, true)
        const pending = bridge.list()
        // Resolved actions don't appear in the list
        expect(pending).toHaveLength(0)
      })

      it('throws on unknown ID', () => {
        expect(() => bridge.resolve('nonexistent', true)).toThrow('Unknown pending action')
      })

      it('throws on double-resolve', async () => {
        const { id, promise } = bridge.requestPermission('Bash', {})
        bridge.resolve(id, true)
        await promise
        expect(() => bridge.resolve(id, true)).toThrow('already resolved')
      })
    })

    describe('timeout', () => {
      it('auto-denies after maxPendingMs', async () => {
        vi.useFakeTimers()
        const shortBridge = createPermissionBridge({ maxPendingMs: 100 })
        const { promise } = shortBridge.requestPermission('Bash', {})

        vi.advanceTimersByTime(100)
        const decision = await promise
        expect(decision).toBe(false)

        vi.useRealTimers()
      })

      it('clears timeout on manual resolve', async () => {
        vi.useFakeTimers()
        const shortBridge = createPermissionBridge({ maxPendingMs: 1000 })
        const { id, promise } = shortBridge.requestPermission('Bash', {})

        shortBridge.resolve(id, true)
        await promise

        // Advance past original timeout; should not change the already-resolved decision
        vi.advanceTimersByTime(1000)
        const decision = await promise
        expect(decision).toBe(true)

        vi.useRealTimers()
      })
    })

    describe('list', () => {
      it('returns empty list initially', () => {
        const pending = bridge.list()
        expect(pending).toEqual([])
      })

      it('lists all pending actions', () => {
        bridge.requestPermission('Bash', { command: 'cmd1' })
        bridge.requestPermission('Edit', { file_path: 'file.js' })
        bridge.requestPermission('Read', { file_path: 'read.txt' })

        const pending = bridge.list()
        // Read-only auto-allows, so only 2 pending
        expect(pending).toHaveLength(2)
        expect(pending[0].toolName).toBe('Bash')
        expect(pending[1].toolName).toBe('Edit')
      })

      it('does not include resolved actions', () => {
        const { id } = bridge.requestPermission('Bash', {})
        bridge.resolve(id, true)
        const pending = bridge.list()
        expect(pending).toHaveLength(0)
      })
    })
  })
})
