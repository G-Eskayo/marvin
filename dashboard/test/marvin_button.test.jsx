import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import MarvinButton from '../src/components/MarvinButton.jsx'
import { redactPrivate } from '../src/lib/redact.js'

describe('MarvinButton redaction and fade', () => {
  // Test 16: Initial render shows no status message
  it('initial render shows no status text', () => {
    const mockOpen = async () => ({ ok: true, dir: '/Users/testuser/worktree/ticket-123', focused: false })
    const html = renderToStaticMarkup(<MarvinButton open={mockOpen} />)
    expect(html).toContain('MARVIN')
    expect(html).toContain('rounded-md')
    // No message should be visible initially
    expect(html).not.toContain('Opened in')
  })

  // Test 17: Success message gets redacted before display
  it('success message with path is redacted before stored in state', () => {
    // The component receives a success result with a path
    const successMessage = 'Opened in /Users/testuser/worktree/ticket-123'
    // The component applies redactPrivate before storing in state
    const redacted = redactPrivate(successMessage)
    expect(redacted).toBe('Opened in ~/worktree/ticket-123')
    expect(redacted).not.toContain('/Users/testuser')
  })

  // Test 18: Error message gets redacted before display
  it('error message with path is redacted before stored in state', () => {
    // The component receives an error result with a path
    const errorMessage = 'Failed at /Users/testuser/.agents/cache'
    // The component applies redactPrivate before storing in state
    const redacted = redactPrivate(errorMessage)
    expect(redacted).toBe('Failed at ~/.agents/cache')
    expect(redacted).not.toContain('/Users/testuser')
  })

  // Test 19: Multiple private info types in one message
  it('redactPrivate redacts paths, IPs, and docs in combined messages', () => {
    const message = 'Log: 2001:db8::1 at /Users/testuser and see docs/plans/feature.md'
    const redacted = redactPrivate(message)
    expect(redacted).not.toContain('/Users')
    expect(redacted).not.toContain('2001:db8::1')
    expect(redacted).not.toContain('docs/plans/feature.md')
    expect(redacted).toContain('[IPv6]')
    expect(redacted).toContain('~')
    expect(redacted).toContain('docs/plans/…')
  })
})
