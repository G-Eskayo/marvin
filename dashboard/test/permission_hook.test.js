import { describe, it, expect } from 'vitest'
import { buildHookOutput } from '../mobile-backend/permission_hook.js'

describe('permission_hook', () => {
  describe('buildHookOutput', () => {
    it('builds allow decision output', () => {
      const output = buildHookOutput({ decision: 'allow' }, 'Read')
      const parsed = JSON.parse(output)
      expect(parsed.hookSpecificOutput.hookEventName).toBe('PreToolUse')
      expect(parsed.hookSpecificOutput.permissionDecision).toBe('allow')
      expect(parsed.hookSpecificOutput.permissionDecisionReason).toContain('Read')
    })

    it('builds deny decision output', () => {
      const output = buildHookOutput({ decision: 'deny', reason: 'timed_out' }, 'Bash')
      const parsed = JSON.parse(output)
      expect(parsed.hookSpecificOutput.hookEventName).toBe('PreToolUse')
      expect(parsed.hookSpecificOutput.permissionDecision).toBe('deny')
      expect(parsed.hookSpecificOutput.permissionDecisionReason).toContain('timed_out')
    })

    it('builds deny decision with denied reason', () => {
      const output = buildHookOutput({ decision: 'deny', reason: 'denied' }, 'Edit')
      const parsed = JSON.parse(output)
      expect(parsed.hookSpecificOutput.permissionDecision).toBe('deny')
      expect(parsed.hookSpecificOutput.permissionDecisionReason).toContain('denied')
    })

    it('includes tool name in reason message', () => {
      const output = buildHookOutput({ decision: 'allow' }, 'WebSearch')
      const parsed = JSON.parse(output)
      expect(parsed.hookSpecificOutput.permissionDecisionReason).toContain('WebSearch')
    })
  })
})
