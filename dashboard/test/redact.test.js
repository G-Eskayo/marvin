import { describe, it, expect } from 'vitest'
import { redactPrivate } from '../src/lib/redact.js'

describe('redactPrivate', () => {
  // IPv6 tests (1-4)
  it('redacts IPv6 addresses', () => {
    expect(redactPrivate('Connection from 2001:db8::1')).toBe('Connection from [IPv6]')
    expect(redactPrivate('2001:0db8:85a3:0000:0000:8a2e:0370:7334')).toBe('[IPv6]')
  })

  it('redacts IPv6 with leading zeros', () => {
    expect(redactPrivate('fe80::1')).toBe('[IPv6]')
  })

  it('preserves text around IPv6', () => {
    expect(redactPrivate('server 2001:db8::1 is live')).toBe('server [IPv6] is live')
  })

  it('redacts multiple IPv6 addresses', () => {
    expect(redactPrivate('2001:db8::1 and fe80::2')).toBe('[IPv6] and [IPv6]')
  })

  it('does not redact timestamps like HH:MM:SS', () => {
    expect(redactPrivate('Log timestamp 12:30:45 is fine')).toBe('Log timestamp 12:30:45 is fine')
    expect(redactPrivate('12:00:03')).toBe('12:00:03')
  })

  // IPv4 tests (5-8)
  it('redacts IPv4 addresses', () => {
    expect(redactPrivate('192.168.1.1')).toBe('[IPv4]')
  })

  it('redacts IPv4 in text', () => {
    expect(redactPrivate('Connect to 10.0.0.5 now')).toBe('Connect to [IPv4] now')
  })

  it('preserves non-IP dots', () => {
    expect(redactPrivate('version 1.2.3 is stable')).toBe('version 1.2.3 is stable')
  })

  it('redacts multiple IPv4 addresses', () => {
    expect(redactPrivate('192.168.1.1 and 10.0.0.5')).toBe('[IPv4] and [IPv4]')
  })

  // File path tests (9-10)
  it('redacts /Users/<name> paths to ~', () => {
    expect(redactPrivate('/Users/alice/.config')).toBe('~/.config')
    expect(redactPrivate('/Users/bob/Projects')).toBe('~/Projects')
  })

  it('redacts multiple user paths', () => {
    expect(redactPrivate('Files in /Users/alice and /Users/bob')).toBe('Files in ~ and ~')
  })

  // Plan docs tests (11-13)
  it('redacts docs/plans/<slug>.md to docs/plans/…', () => {
    expect(redactPrivate('See docs/plans/my-feature.md for details')).toBe('See docs/plans/… for details')
  })

  it('redacts multiple plan paths', () => {
    expect(redactPrivate('docs/plans/alpha.md and docs/plans/beta.md')).toBe('docs/plans/… and docs/plans/…')
  })

  it('only redacts docs/plans patterns, not other docs', () => {
    expect(redactPrivate('docs/guides/api.md')).toBe('docs/guides/api.md')
  })
})
