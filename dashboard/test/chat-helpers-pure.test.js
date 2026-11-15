import { describe, it, expect } from 'vitest'
import { HOME_CAP, DISMISSED_KEY, dismissKey, visibleHelpers, pruneDismissed } from '../src/components/ChatHelpers.jsx'

describe('ChatHelpers pure functions (Tests 6-10)', () => {
  // Test 6: HOME_CAP and DISMISSED_KEY are exported
  it('HOME_CAP and DISMISSED_KEY are exported', () => {
    expect(HOME_CAP).toBe(10)
    expect(DISMISSED_KEY).toBe('chatHelpers.dismissed.v1')
  })

  // Test 7: dismissKey generates unique keys per helper
  it('dismissKey generates unique keys for each helper', () => {
    const h1 = { id: 'helper-1', machine: 'macbook-pro' }
    const h2 = { id: 'helper-1', machine: 'mac-mini-1' }
    const h3 = { id: 'helper-2', machine: 'macbook-pro' }

    expect(dismissKey(h1)).toBe('macbook-pro:helper-1')
    expect(dismissKey(h2)).toBe('mac-mini-1:helper-1')
    expect(dismissKey(h3)).toBe('macbook-pro:helper-2')

    // Same helper gets same key
    expect(dismissKey(h1)).toBe(dismissKey(h1))

    // Different helpers get different keys
    expect(dismissKey(h1)).not.toBe(dismissKey(h2))
  })

  // Test 8: visibleHelpers prioritizes running helpers and respects cap
  it('visibleHelpers keeps all running, fills remaining with others, respects cap', () => {
    const helpers = [
      { id: 'h1', machine: 'mac1', status: 'running' },
      { id: 'h2', machine: 'mac1', status: 'crashed' },
      { id: 'h3', machine: 'mac1', status: 'done' },
      { id: 'h4', machine: 'mac1', status: 'running' },
      { id: 'h5', machine: 'mac1', status: 'crashed' }
    ]

    // No dismissals: should show all running first (h1, h4), then others (h2, h3, h5)
    const visible = visibleHelpers(helpers)
    expect(visible.length).toBe(5)
    expect(visible.slice(0, 2).map(h => h.id)).toEqual(['h1', 'h4'])  // running first
    expect(visible.slice(2).map(h => h.id)).toEqual(['h2', 'h3', 'h5'])  // then others

    // Dismiss h2 (crashed): remaining are h1,h3,h4,h5 -> 2 running, 2 others
    const dismissed = { 'mac1:h2': true }
    const visible2 = visibleHelpers(helpers, dismissed)
    expect(visible2.map(h => h.id)).toEqual(['h1', 'h4', 'h3', 'h5'])

    // With cap=2: keep all running (h1, h4), none for others
    const visible3 = visibleHelpers(helpers, dismissed, 2)
    expect(visible3.map(h => h.id)).toEqual(['h1', 'h4'])

    // All dismissed
    const allDismissed = { 'mac1:h1': true, 'mac1:h2': true, 'mac1:h3': true, 'mac1:h4': true, 'mac1:h5': true }
    expect(visibleHelpers(helpers, allDismissed)).toEqual([])
  })

  // Test 9: visibleHelpers handles edge cases
  it('visibleHelpers handles null/undefined inputs gracefully', () => {
    expect(visibleHelpers(null)).toEqual([])
    expect(visibleHelpers(undefined)).toEqual([])
    expect(visibleHelpers([])).toEqual([])
    expect(visibleHelpers([{ id: 'h1', machine: 'm1' }], null)).toEqual([{ id: 'h1', machine: 'm1' }])
    expect(visibleHelpers([{ id: 'h1', machine: 'm1' }], undefined)).toEqual([{ id: 'h1', machine: 'm1' }])
  })

  // Test 10: pruneDismissed removes stale entries
  it('pruneDismissed removes entries not in helpers list', () => {
    const helpers = [
      { id: 'h1', machine: 'mac1' },
      { id: 'h2', machine: 'mac1' },
      { id: 'h3', machine: 'mac1' }
    ]

    const dismissed = {
      'mac1:h1': true,
      'mac1:h2': true,
      'mac1:h4': true,  // This helper no longer exists
      'mac2:h1': true   // Different machine, also gone
    }

    const pruned = pruneDismissed(dismissed, helpers)

    // Only entries for helpers that still exist remain
    expect(pruned).toEqual({
      'mac1:h1': true,
      'mac1:h2': true
    })

    // Empty result returns null
    const nothingDismissed = { 'mac1:h4': true, 'mac1:h5': true }
    expect(pruneDismissed(nothingDismissed, helpers)).toBeNull()

    // No dismissals = return input
    const empty = {}
    expect(pruneDismissed(empty, helpers)).toBeNull()
  })

  // Defect #1: pruneDismissed should return same reference when no changes occur
  // (prevents endless refetch loop)
  it('pruneDismissed returns same reference when no entries were pruned (Defect #1)', () => {
    const helpers = [
      { id: 'h1', machine: 'mac1' },
      { id: 'h2', machine: 'mac1' }
    ]

    const dismissed = {
      'mac1:h1': true,
      'mac1:h2': true
    }

    // All dismissed entries are still in helpers, so no pruning needed
    const pruned = pruneDismissed(dismissed, helpers)

    // Should return the SAME object reference, not a new one
    expect(pruned).toBe(dismissed)
  })

  // Defect #2: pruneDismissed should preserve entries for unreachable machines
  // (prevents lost dismissals when a Mac drops off briefly)
  it('pruneDismissed preserves entries for unreachable machines (Defect #2)', () => {
    const helpers = [
      { id: 'h1', machine: 'mac1' },
      { id: 'h2', machine: 'mac1' }
    ]

    const dismissed = {
      'mac1:h1': true,
      'mac1:h2': true,
      'mac-mini:h3': true  // This helper from mac-mini is dismissed
    }

    const unreachable = new Set(['mac-mini'])  // mac-mini is currently unreachable

    const pruned = pruneDismissed(dismissed, helpers, unreachable)

    // Should keep mac1 helpers (they're in the current list)
    // AND keep mac-mini helper (it's unreachable, so might reconnect later)
    expect(pruned).toEqual({
      'mac1:h1': true,
      'mac1:h2': true,
      'mac-mini:h3': true  // Preserved even though not in current helpers
    })
  })

  it('pruneDismissed removes entries for machines that are no longer unreachable', () => {
    const helpers = [
      { id: 'h1', machine: 'mac1' },
      { id: 'h2', machine: 'mac1' },
      { id: 'h4', machine: 'mac-mini' }  // mac-mini is back and has h4, but not h3
    ]

    const dismissed = {
      'mac1:h1': true,
      'mac1:h2': true,
      'mac-mini:h3': true,  // Dismissed helper from mac-mini (no longer exists)
      'mac-mini:h4': true   // Dismissed helper from mac-mini (still exists)
    }

    const unreachable = new Set()  // mac-mini is reachable now

    const pruned = pruneDismissed(dismissed, helpers, unreachable)

    // Keep mac1 helpers (in list), keep mac-mini:h4 (in list)
    // Remove mac-mini:h3 (not in list and mac-mini is reachable)
    expect(pruned).toEqual({
      'mac1:h1': true,
      'mac1:h2': true,
      'mac-mini:h4': true
    })
  })
})
