import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  isReadOnlyTool,
  summarize,
  createPendingActionStore,
  requestPermission,
  DEFAULT_TIMEOUT_MS
} from '../mobile-backend/permission_bridge.js'

describe('permission_bridge', () => {
  describe('isReadOnlyTool', () => {
    it('returns true for Read tool', () => {
      expect(isReadOnlyTool('Read')).toBe(true)
      expect(isReadOnlyTool('read')).toBe(true)
      expect(isReadOnlyTool('READ')).toBe(true)
    })

    it('returns true for Grep tool', () => {
      expect(isReadOnlyTool('Grep')).toBe(true)
      expect(isReadOnlyTool('grep')).toBe(true)
    })

    it('returns true for Glob tool', () => {
      expect(isReadOnlyTool('Glob')).toBe(true)
    })

    it('returns true for WebFetch tool', () => {
      expect(isReadOnlyTool('WebFetch')).toBe(true)
      expect(isReadOnlyTool('webfetch')).toBe(true)
    })

    it('returns true for WebSearch tool', () => {
      expect(isReadOnlyTool('WebSearch')).toBe(true)
    })

    it('returns false for Bash tool', () => {
      expect(isReadOnlyTool('Bash')).toBe(false)
    })

    it('returns false for Edit tool', () => {
      expect(isReadOnlyTool('Edit')).toBe(false)
    })

    it('returns false for Write tool', () => {
      expect(isReadOnlyTool('Write')).toBe(false)
    })

    it('returns false for unknown tools', () => {
      expect(isReadOnlyTool('Unknown')).toBe(false)
      expect(isReadOnlyTool('CustomTool')).toBe(false)
    })
  })

  describe('summarize', () => {
    it('summarizes Bash commands', () => {
      const summary = summarize('Bash', { command: 'ls -la /tmp' })
      expect(summary).toMatch(/Run:/)
      expect(summary).toMatch(/ls -la/)
    })

    it('truncates long Bash commands', () => {
      const longCmd = 'echo ' + 'x'.repeat(100)
      const summary = summarize('Bash', { command: longCmd })
      expect(summary.length).toBeLessThanOrEqual(60)
    })

    it('summarizes Edit operations', () => {
      const summary = summarize('Edit', { file_path: '/path/to/file.js' })
      expect(summary).toMatch(/Edit.*file\.js/)
    })

    it('summarizes Write operations', () => {
      const summary = summarize('Write', { file_path: '/path/to/new_file.txt' })
      expect(summary).toMatch(/Write.*new_file\.txt/)
    })

    it('handles missing file_path gracefully', () => {
      const summary = summarize('Edit', {})
      expect(summary).toMatch(/Edit/)
    })

    it('fallback for unknown tools', () => {
      const summary = summarize('CustomTool', {})
      expect(summary).toMatch(/CustomTool/)
    })
  })

  describe('PendingActionStore', () => {
    let store

    beforeEach(() => {
      store = createPendingActionStore()
    })

    it('creates a pending action', () => {
      const action = store.create('Bash', { command: 'test' }, 'Run: `test`')
      expect(action.id).toBeDefined()
      expect(action.toolName).toBe('Bash')
      expect(action.toolInput).toEqual({ command: 'test' })
      expect(action.summary).toBe('Run: `test`')
      expect(action.status).toBe('pending')
      expect(action.createdAt).toBeDefined()
    })

    it('retrieves a pending action by ID', () => {
      const created = store.create('Bash', { command: 'test' }, 'summary')
      const retrieved = store.get(created.id)
      expect(retrieved).toEqual(created)
    })

    it('returns null for unknown ID', () => {
      expect(store.get('unknown-id')).toBe(null)
    })

    it('lists all pending actions', () => {
      store.create('Bash', { command: 'test1' }, 'summary1')
      store.create('Edit', { file_path: 'file.js' }, 'summary2')
      const all = store.list()
      expect(all).toHaveLength(2)
      expect(all[0].summary).toBe('summary1')
      expect(all[1].summary).toBe('summary2')
    })

    it('resolves an action as approved', () => {
      const created = store.create('Bash', { command: 'test' }, 'summary')
      const result = store.resolve(created.id, 'approved')
      expect(result.status).toBe('approved')
      expect(result.resolvedAt).toBeDefined()
    })

    it('resolves an action as denied', () => {
      const created = store.create('Bash', { command: 'test' }, 'summary')
      const result = store.resolve(created.id, 'denied')
      expect(result.status).toBe('denied')
    })

    it('resolves an action as timed_out', () => {
      const created = store.create('Bash', { command: 'test' }, 'summary')
      const result = store.resolve(created.id, 'timed_out')
      expect(result.status).toBe('timed_out')
    })

    it('returns null when resolving unknown ID', () => {
      const result = store.resolve('unknown-id', 'approved')
      expect(result).toBe(null)
    })

    it('removes resolved actions from list', () => {
      const created = store.create('Bash', { command: 'test' }, 'summary')
      store.resolve(created.id, 'approved')
      const all = store.list()
      expect(all).toHaveLength(0)
    })
  })

  describe('requestPermission', () => {
    let store

    beforeEach(() => {
      store = createPendingActionStore()
    })

    it('immediately approves read-only tools without creating a pending action', async () => {
      const result = await requestPermission('Read', { file_path: '/tmp/test' }, { store })
      expect(result.decision).toBe('allow')
      expect(result.actionId).toBeUndefined()
      expect(store.list()).toHaveLength(0)
    })

    it('creates a pending action for side-effecting tools', async () => {
      const promise = requestPermission('Bash', { command: 'test' }, { store, timeoutMs: 1000 })
      // Give a moment for the action to be created
      await new Promise(resolve => setTimeout(resolve, 10))
      expect(store.list()).toHaveLength(1)
      // Clean up the pending request
      const action = store.list()[0]
      store.resolve(action.id, 'denied')
      await promise
    })

    it('returns decision when action is approved via store.resolve', async () => {
      const promise = requestPermission('Bash', { command: 'test' }, { store, timeoutMs: 5000 })
      // Give a moment for the action to be created
      await new Promise(resolve => setTimeout(resolve, 10))
      const action = store.list()[0]
      store.resolve(action.id, 'approved')
      const result = await promise
      expect(result.decision).toBe('allow')
      expect(result.actionId).toBe(action.id)
    })

    it('returns deny decision when action is denied', async () => {
      const promise = requestPermission('Bash', { command: 'test' }, { store, timeoutMs: 5000 })
      // Give a moment for the action to be created
      await new Promise(resolve => setTimeout(resolve, 10))
      const action = store.list()[0]
      store.resolve(action.id, 'denied')
      const result = await promise
      expect(result.decision).toBe('deny')
      expect(result.reason).toBe('denied')
    })

    it('defaults to deny on timeout', async () => {
      const result = await requestPermission('Bash', { command: 'test' }, { store, timeoutMs: 50 })
      expect(result.decision).toBe('deny')
      expect(result.reason).toBe('timed_out')
    })

    it('uses DEFAULT_TIMEOUT_MS if timeoutMs not provided', async () => {
      // This test just ensures the function accepts no timeoutMs and uses the default
      const promise = requestPermission('Bash', { command: 'test' }, { store })
      await new Promise(resolve => setTimeout(resolve, 10))
      const action = store.list()[0]
      store.resolve(action.id, 'approved')
      const result = await promise
      expect(result.decision).toBe('allow')
    })
  })
})
