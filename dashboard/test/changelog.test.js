import { describe, it, expect, vi, beforeEach } from 'vitest'
import { bumpType, bumpVersion, formatChangelogEntry } from '../webhook-server/changelog.js'

describe('bumpType', () => {
  it('returns major when breaking-change is present', () => {
    expect(bumpType(['enhancement', 'breaking-change'])).toBe('major')
    expect(bumpType(['breaking-change'])).toBe('major')
  })

  it('returns minor when enhancement is present (but not breaking-change)', () => {
    expect(bumpType(['enhancement'])).toBe('minor')
    expect(bumpType(['enhancement', 'bug-fix'])).toBe('minor')
  })

  it('returns patch when neither breaking-change nor enhancement is present', () => {
    expect(bumpType([])).toBe('patch')
    expect(bumpType(['bug-fix'])).toBe('patch')
    expect(bumpType(['documentation'])).toBe('patch')
  })

  it('breaking-change wins when both enhancement and breaking-change are present', () => {
    expect(bumpType(['enhancement', 'breaking-change'])).toBe('major')
  })

  it('handles undefined labels gracefully', () => {
    expect(bumpType()).toBe('patch')
  })
})

describe('bumpVersion', () => {
  it('bumps major version and resets minor and patch', () => {
    expect(bumpVersion('1.2.3', 'major')).toBe('2.0.0')
    expect(bumpVersion('0.0.0', 'major')).toBe('1.0.0')
    expect(bumpVersion('9.9.9', 'major')).toBe('10.0.0')
  })

  it('bumps minor version and resets patch', () => {
    expect(bumpVersion('1.2.3', 'minor')).toBe('1.3.0')
    expect(bumpVersion('0.0.0', 'minor')).toBe('0.1.0')
    expect(bumpVersion('1.9.9', 'minor')).toBe('1.10.0')
  })

  it('bumps patch version only', () => {
    expect(bumpVersion('1.2.3', 'patch')).toBe('1.2.4')
    expect(bumpVersion('0.0.0', 'patch')).toBe('0.0.1')
    expect(bumpVersion('9.9.9', 'patch')).toBe('9.9.10')
  })

  it('throws on invalid version format', () => {
    expect(() => bumpVersion('1.2', 'patch')).toThrow(/Invalid version format/)
    expect(() => bumpVersion('1.2.3.4', 'patch')).toThrow(/Invalid version format/)
    expect(() => bumpVersion('a.b.c', 'patch')).toThrow(/Invalid version format/)
    expect(() => bumpVersion('1.2.x', 'patch')).toThrow(/Invalid version format/)
  })

  it('throws on invalid bump type', () => {
    expect(() => bumpVersion('1.2.3', 'minor-major')).toThrow(/Invalid bump type/)
    expect(() => bumpVersion('1.2.3', 'invalid')).toThrow(/Invalid bump type/)
  })
})

describe('formatChangelogEntry', () => {
  it('formats a changelog entry with a date string', () => {
    const entry = formatChangelogEntry('1.0.0', 'Add new feature', 'https://github.com/G-Eskayo/marvin/pull/42', '2026-10-09')
    expect(entry).toBe('- Add new feature ([PR](https://github.com/G-Eskayo/marvin/pull/42))')
  })

  it('formats a changelog entry with a Date object', () => {
    const date = new Date('2026-10-09T12:34:56Z')
    const entry = formatChangelogEntry('1.0.0', 'Fix bug', 'https://github.com/G-Eskayo/marvin/pull/43', date)
    expect(entry).toBe('- Fix bug ([PR](https://github.com/G-Eskayo/marvin/pull/43))')
  })

  it('escapes special characters in title if present', () => {
    const entry = formatChangelogEntry('1.0.0', 'Add [feature] with (parens)', 'https://github.com/G-Eskayo/marvin/pull/44', '2026-10-09')
    expect(entry).toContain('Add [feature] with (parens)')
  })
})
