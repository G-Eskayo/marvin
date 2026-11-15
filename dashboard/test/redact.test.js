import { describe, it, expect } from 'vitest'
import { redactText } from '../src/lib/redact.js'

describe('redactText', () => {
  describe('home path redaction', () => {
    it('redacts macOS home paths to ~', () => {
      expect(redactText('/Users/gileskayo/.claude')).toBe('~/.claude')
      expect(redactText('/Users/gileskayo/some/path/file.txt')).toBe('~/some/path/file.txt')
    })

    it('redacts Linux home paths to ~', () => {
      expect(redactText('/home/bob/.agents')).toBe('~/.agents')
      expect(redactText('/home/bob/Desktop/file.md')).toBe('~/Desktop/file.md')
    })

    it('redacts Windows home paths to ~', () => {
      expect(redactText('C:\\Users\\alice\\Documents')).toBe('~\\Documents')
      expect(redactText('C:\\Users\\alice\\code\\project')).toBe('~\\code\\project')
    })

    it('is case-insensitive on Windows paths', () => {
      expect(redactText('C:\\USERS\\ALICE\\DOCUMENTS')).toBe('~\\DOCUMENTS')
      expect(redactText('c:\\users\\alice\\file.txt')).toBe('~\\file.txt')
    })

    it('does not redact paths that do not match home pattern', () => {
      expect(redactText('/var/log/file.txt')).toBe('/var/log/file.txt')
      expect(redactText('/tmp/data')).toBe('/tmp/data')
    })
  })

  describe('IPv4 redaction', () => {
    it('redacts IPv4 addresses', () => {
      expect(redactText('192.168.1.1')).toBe('192.168.***.***.***')
      expect(redactText('10.0.0.1')).toBe('10.0.***.***.***')
      expect(redactText('Connected to 192.168.1.100')).toBe('Connected to 192.168.***.***.***')
    })

    it('handles multiple IPv4 addresses in text', () => {
      expect(redactText('ping 192.168.1.1 from 10.0.0.1')).toBe('ping 192.168.***.***.*** from 10.0.***.***.***')
    })

    it('avoids false positives in duration text', () => {
      // Patterns like "0:05:31" (duration) should not trigger redaction
      expect(redactText('took 0:05:31 to complete')).toBe('took 0:05:31 to complete')
      expect(redactText('ran in 0:01:45 time')).toBe('ran in 0:01:45 time')
    })
  })

  describe('IPv6 redaction', () => {
    it('redacts IPv6 addresses', () => {
      expect(redactText('fe80::1')).toBe('***:***:***')
      expect(redactText('2001:db8::1')).toBe('***:***:***')
      expect(redactText('::1')).toBe('***:***:***')
    })

    it('handles IPv6 in context', () => {
      expect(redactText('Connected to fe80::1 via IPv6')).toBe('Connected to ***:***:*** via IPv6')
    })
  })

  describe('hostname/IP resolution with registry', () => {
    const registry = {
      'mac-mini-1': { display_name: 'Mini', display: 'mac-mini-1', name: 'mini' },
      '192.168.1.10': { display_name: 'MBP', display: 'macbook-pro-1', name: 'mbp' }
    }

    it('redacts Tailscale IPs to device name even without registry', () => {
      expect(redactText('100.68.1.1')).toBe('(device)')
      expect(redactText('100.127.255.255')).toBe('(device)')
    })

    it('masks regular private IPs without registry entry', () => {
      expect(redactText('10.0.0.1')).toBe('10.0.***.***.***')
      expect(redactText('192.168.1.1')).toBe('192.168.***.***.***')
    })

    it('uses registry display_name if IP is in registry', () => {
      expect(redactText('192.168.1.10 is the host', { registry })).toBe('(device) is the host')
    })

    it('handles hostnames that match registry keys', () => {
      const reg = { 'mini.local': { display: 'Mini' } }
      expect(redactText('connected to mini.local', { registry: reg })).toBe('connected to (device)')
    })
  })

  describe('filename redaction', () => {
    it('redacts docs/plans/ filenames', () => {
      expect(redactText('docs/plans/my-feature.md')).toBe('(docs/plans)')
      expect(redactText('See docs/plans/roadmap-2026.md for details')).toBe('See (docs/plans) for details')
    })

    it('redacts handoff-dated-slug.md filenames', () => {
      expect(redactText('handoff-2026-11-15-my-task.md')).toBe('(handoff)')
      expect(redactText('handoff-2026-11-15.md')).toBe('(handoff)')
      expect(redactText('Check handoff-2026-10-01-cleanup-sweep.md')).toBe('Check (handoff)')
    })

    it('does not redact filenames that do not match the pattern', () => {
      expect(redactText('README.md')).toBe('README.md')
      expect(redactText('src/main.js')).toBe('src/main.js')
    })
  })

  describe('combined redaction', () => {
    it('redacts multiple types in one text', () => {
      const text = 'Error at /Users/bob/.claude/cache on host 192.168.1.1 in docs/plans/debug.md'
      expect(redactText(text)).toBe('Error at ~/.claude/cache on host 192.168.***.***.*** in (docs/plans)')
    })

    it('handles edge cases with mixed content', () => {
      const text = 'Sync /home/alice/data from 10.0.0.5 (handoff-2026-11-15-sync.md)'
      expect(redactText(text)).toBe('Sync ~/data from 10.0.***.***.*** (handoff)')
    })
  })

  describe('edge cases', () => {
    it('handles null and undefined', () => {
      expect(redactText(null)).toBe('')
      expect(redactText(undefined)).toBe('')
    })

    it('handles empty string', () => {
      expect(redactText('')).toBe('')
    })

    it('converts non-string inputs to string', () => {
      expect(redactText(123)).toBe('123')
      expect(redactText(true)).toBe('true')
    })

    it('preserves normal text', () => {
      expect(redactText('This is a normal message')).toBe('This is a normal message')
    })
  })
})
