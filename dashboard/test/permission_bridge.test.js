import { describe, it, expect } from 'vitest'
import { classifyTool, summarize, createPermissionBridge } from '../mobile-backend/permission_bridge.js'

describe('classifyTool', () => {
  it('classifies read-only tools as read', () => {
    expect(classifyTool('Read')).toBe('read')
    expect(classifyTool('Grep')).toBe('read')
    expect(classifyTool('Glob')).toBe('read')
    expect(classifyTool('WebSearch')).toBe('read')
  })

  it('classifies all other tools as side-effecting', () => {
    expect(classifyTool('Bash')).toBe('side-effecting')
    expect(classifyTool('Write')).toBe('side-effecting')
    expect(classifyTool('Edit')).toBe('side-effecting')
    expect(classifyTool('WebFetch')).toBe('side-effecting')
    expect(classifyTool('mcp__foo__bar')).toBe('side-effecting')
    expect(classifyTool('UnknownTool')).toBe('side-effecting')
  })
})

describe('summarize', () => {
  it('summarizes Bash commands', () => {
    expect(summarize('Bash', { command: 'ls -la' })).toBe('Run: ls -la')
    expect(summarize('Bash', {})).toBe('Run a bash command')
  })

  it('summarizes Write/Edit operations', () => {
    expect(summarize('Write', { file_path: '/foo/bar.txt' })).toBe('Edit /foo/bar.txt')
    expect(summarize('Edit', { file_path: '/foo/bar.js' })).toBe('Edit /foo/bar.js')
  })

  it('summarizes Read operations', () => {
    expect(summarize('Read', { file_path: '/foo/bar.txt' })).toBe('Read /foo/bar.txt')
  })

  it('summarizes search operations', () => {
    expect(summarize('Grep', { pattern: 'foo' })).toBe('Search for foo')
    expect(summarize('Glob', { pattern: '*.js' })).toBe('Find files matching *.js')
    expect(summarize('WebSearch', { query: 'node.js' })).toBe('Search: node.js')
  })

  it('provides fallback summaries', () => {
    expect(summarize('Write', {})).toBe('Edit a file')
    expect(summarize('Read', {})).toBe('Read a file')
    expect(summarize('Grep', {})).toBe('Search files')
    expect(summarize('WebFetch', { url: 'https://example.com' })).toBe('Fetch https://example.com')
    expect(summarize('UnknownTool', {})).toBe('Use UnknownTool')
  })
})

describe('permission bridge', () => {
  describe('read-only tools are immediately allowed', () => {
    it('returns allow behavior without creating pending action', async () => {
      const bridge = createPermissionBridge()
      const result = await bridge.requestPermission({
        toolName: 'Read',
        input: { file_path: '/foo/bar' },
        requestId: 'req-123'
      })
      expect(result).toEqual({ behavior: 'allow' })
      expect(bridge.list()).toHaveLength(0)
    })

    it('allows all read-only tools immediately', async () => {
      const bridge = createPermissionBridge()
      for (const toolName of ['Read', 'Grep', 'Glob', 'WebSearch']) {
        const result = await bridge.requestPermission({
          toolName,
          input: {},
          requestId: `req-${toolName}`
        })
        expect(result).toEqual({ behavior: 'allow' })
      }
      expect(bridge.list()).toHaveLength(0)
    })
  })

  describe('side-effecting tools create pending actions', () => {
    it('creates a pending action and returns a promise', () => {
      const bridge = createPermissionBridge()
      const promise = bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'rm -rf /' },
        requestId: 'req-bash'
      })
      expect(promise instanceof Promise).toBe(true)
      const pending = bridge.list()
      expect(pending).toHaveLength(1)
      expect(pending[0].toolName).toBe('Bash')
      expect(pending[0].summary).toBe('Run: rm -rf /')
    })

    it('pending actions have id, toolName, summary, createdAt, requestId', () => {
      const bridge = createPermissionBridge()
      const t0 = Date.now()
      bridge.requestPermission({
        toolName: 'Edit',
        input: { file_path: '/sensitive/file' },
        requestId: 'req-edit'
      }, t0)
      const [action] = bridge.list()
      expect(action).toMatchObject({
        id: expect.stringMatching(/^perm_\d+$/),
        toolName: 'Edit',
        summary: 'Edit /sensitive/file',
        createdAt: t0,
        requestId: 'req-edit'
      })
    })

    it('multiple pending actions get unique ids', () => {
      const bridge = createPermissionBridge()
      const p1 = bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'cmd1' },
        requestId: 'req1'
      })
      const p2 = bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'cmd2' },
        requestId: 'req2'
      })
      const pending = bridge.list()
      expect(pending).toHaveLength(2)
      expect(pending[0].id).not.toBe(pending[1].id)
    })
  })

  describe('resolving pending actions', () => {
    it('approves a pending action and resolves its promise', async () => {
      const bridge = createPermissionBridge()
      const promise = bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'ls' },
        requestId: 'req-1'
      })
      const [action] = bridge.list()
      bridge.resolve(action.id, true)
      const result = await promise
      expect(result).toEqual({ behavior: 'allow' })
      expect(bridge.list()).toHaveLength(0)
    })

    it('denies a pending action and resolves its promise', async () => {
      const bridge = createPermissionBridge()
      const promise = bridge.requestPermission({
        toolName: 'Write',
        input: { file_path: '/etc/passwd' },
        requestId: 'req-1'
      })
      const [action] = bridge.list()
      bridge.resolve(action.id, false)
      const result = await promise
      expect(result).toEqual({ behavior: 'deny' })
      expect(bridge.list()).toHaveLength(0)
    })

    it('returns false if trying to resolve unknown action', () => {
      const bridge = createPermissionBridge()
      const success = bridge.resolve('perm_unknown', true)
      expect(success).toBe(false)
    })

    it('returns false if trying to resolve already-resolved action', () => {
      const bridge = createPermissionBridge()
      const promise = bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'ls' },
        requestId: 'req-1'
      })
      const [action] = bridge.list()
      expect(bridge.resolve(action.id, true)).toBe(true)
      expect(bridge.resolve(action.id, true)).toBe(false)
    })
  })

  describe('pending actions timeout', () => {
    it('auto-expires after maxPendingMs', () => {
      const bridge = createPermissionBridge({ maxPendingMs: 1000 })
      const t0 = Date.now()
      bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'ls' },
        requestId: 'req-1'
      }, t0)
      expect(bridge.list(t0 + 500)).toHaveLength(1)
      expect(bridge.list(t0 + 5000)).toHaveLength(0)
    })

    it('cannot resolve an expired action', () => {
      const bridge = createPermissionBridge({ maxPendingMs: 1000 })
      const t0 = Date.now()
      const promise = bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'ls' },
        requestId: 'req-1'
      }, t0)
      const [action] = bridge.list(t0)
      const success = bridge.resolve(action.id, true, t0 + 5000)
      expect(success).toBe(false)
    })

    it('respects custom maxPendingMs', () => {
      const bridge = createPermissionBridge({ maxPendingMs: 5000 })
      const t0 = Date.now()
      bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'ls' },
        requestId: 'req-1'
      }, t0)
      expect(bridge.list(t0 + 2000)).toHaveLength(1)
      expect(bridge.list(t0 + 6000)).toHaveLength(0)
    })
  })

  describe('multiple actions lifecycle', () => {
    it('can track and resolve multiple actions independently', async () => {
      const bridge = createPermissionBridge()
      const p1 = bridge.requestPermission({
        toolName: 'Bash',
        input: { command: 'cmd1' },
        requestId: 'req1'
      })
      const p2 = bridge.requestPermission({
        toolName: 'Write',
        input: { file_path: '/file' },
        requestId: 'req2'
      })
      const pending = bridge.list()
      expect(pending).toHaveLength(2)

      bridge.resolve(pending[0].id, true)
      expect(bridge.list()).toHaveLength(1)

      bridge.resolve(pending[1].id, false)
      expect(bridge.list()).toHaveLength(0)
    })
  })
})
