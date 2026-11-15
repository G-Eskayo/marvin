import { describe, it, expect, vi } from 'vitest'
import { stillInList, recheckVanished, applyRecheck } from '../src/lib/selected_pr.js'

// Test the integration of selected_pr functions when an open PR vanishes from the list
describe('PR vanish detection: open PR becomes read-only when it closes while viewing', () => {
  const openPr = {
    number: 810,
    title: 'Implement PR vanish detection',
    url: 'https://github.com/G-Eskayo/marvin/pull/810',
    repo: 'G-Eskayo/marvin',
    key: 'k810',
    readOnly: false,
    state: 'OPEN',
    evidence: null
  }

  const otherPr = {
    number: 811,
    title: 'Another PR',
    url: 'https://github.com/G-Eskayo/marvin/pull/811',
    repo: 'G-Eskayo/marvin',
    key: 'k811'
  }

  describe('Step 1: Check if PR still in list (stillInList)', () => {
    it('returns true when open PR is still in the list', () => {
      const prs = [openPr, otherPr]
      expect(stillInList(openPr, prs)).toBe(true)
    })

    it('returns false when open PR has vanished from list', () => {
      const prs = [otherPr] // openPr is gone
      expect(stillInList(openPr, prs)).toBe(false)
    })

    it('returns false when list is null/empty', () => {
      expect(stillInList(openPr, null)).toBe(false)
      expect(stillInList(openPr, [])).toBe(false)
    })
  })

  describe('Step 2: Recheck status in history (recheckVanished)', () => {
    it('calls historyDetail with the PR URL', async () => {
      const historyDetail = vi.fn().mockResolvedValue({
        state: 'MERGED',
        mergedAt: '2026-11-14T12:00:00Z'
      })
      await recheckVanished(openPr.url, historyDetail)
      expect(historyDetail).toHaveBeenCalledWith(openPr.url)
    })

    it('returns the merged PR data when PR is merged', async () => {
      const historyDetail = vi.fn().mockResolvedValue({
        state: 'MERGED',
        mergedAt: '2026-11-14T12:00:00Z'
      })
      const result = await recheckVanished(openPr.url, historyDetail)
      expect(result.state).toBe('MERGED')
      expect(result.mergedAt).toBe('2026-11-14T12:00:00Z')
    })

    it('returns null if the PR is still open (not vanished)', async () => {
      const historyDetail = vi.fn().mockResolvedValue({
        state: 'OPEN'
      })
      const result = await recheckVanished(openPr.url, historyDetail)
      expect(result).toBeNull()
    })

    it('returns null if the API call fails (network error, etc)', async () => {
      const historyDetail = vi.fn().mockRejectedValue(new Error('Network error'))
      const result = await recheckVanished(openPr.url, historyDetail)
      expect(result).toBeNull()
    })
  })

  describe('Step 3: Apply recheck result to update state (applyRecheck)', () => {
    it('marks the PR as read-only with merged state', () => {
      const fresh = { state: 'MERGED', mergedAt: '2026-11-14T12:00:00Z' }
      const updated = applyRecheck(openPr, openPr, fresh)
      expect(updated.readOnly).toBe(true)
      expect(updated.state).toBe('MERGED')
      expect(updated.mergedAt).toBe('2026-11-14T12:00:00Z')
    })

    it('preserves original PR fields when fresh does not have them', () => {
      const fresh = { state: 'MERGED' }
      const updated = applyRecheck(openPr, openPr, fresh)
      expect(updated.number).toBe(810)
      expect(updated.title).toBe('Implement PR vanish detection')
      expect(updated.url).toBe('https://github.com/G-Eskayo/marvin/pull/810')
    })

    it('returns unchanged PR if fresh is null (recheck failed)', () => {
      const updated = applyRecheck(openPr, openPr, null)
      expect(updated).toBe(openPr)
      expect(updated.readOnly).toBe(false)
    })

    it('protects against stale rechecks: ignores result if user selected a different PR', () => {
      const differentPr = { ...openPr, url: 'https://github.com/G-Eskayo/marvin/pull/812' }
      const fresh = { state: 'MERGED' }
      // asked (what we were checking) != selected (what user is now viewing)
      const updated = applyRecheck(differentPr, openPr, fresh)
      expect(updated).toBe(differentPr) // unchanged
      expect(updated.readOnly).toBe(false)
    })
  })

  describe('Full vanish flow: PR is open, then vanishes, then becomes read-only', () => {
    it('simulates the complete flow from open to vanished to read-only', async () => {
      // Start: PR is open and in the list
      let prs = [openPr, otherPr]
      let selected = openPr
      expect(selected.readOnly).toBe(false)
      expect(stillInList(selected, prs)).toBe(true)

      // PR is closed on GitHub, removed from the open list
      prs = [otherPr]
      expect(stillInList(selected, prs)).toBe(false)

      // Trigger vanish detection (what the useEffect does)
      const historyDetail = vi.fn().mockResolvedValue({
        state: 'MERGED',
        mergedAt: '2026-11-14T12:00:00Z'
      })
      const fresh = await recheckVanished(selected.url, historyDetail)
      expect(fresh).not.toBeNull()

      // Apply the update
      selected = applyRecheck(selected, selected, fresh)
      expect(selected.readOnly).toBe(true)
      expect(selected.state).toBe('MERGED')
    })

    it('handles the case where recheck returns null (PR actually still open, not merged)', async () => {
      let prs = [otherPr] // openPr removed from list, but...
      let selected = openPr
      const historyDetail = vi.fn().mockResolvedValue({
        state: 'OPEN' // PR is still open somewhere else
      })
      const fresh = await recheckVanished(selected.url, historyDetail)
      expect(fresh).toBeNull() // Not merged/closed, so no update

      // PR state should not change
      selected = applyRecheck(selected, selected, fresh)
      expect(selected).toEqual(openPr) // unchanged
      expect(selected.readOnly).toBe(false)
    })

    it('handles the case where the API call fails (transient error)', async () => {
      let prs = [otherPr]
      let selected = openPr
      const historyDetail = vi.fn().mockRejectedValue(new Error('Timeout'))
      const fresh = await recheckVanished(selected.url, historyDetail)
      expect(fresh).toBeNull() // API failed

      // PR state should not change
      selected = applyRecheck(selected, selected, fresh)
      expect(selected).toEqual(openPr) // unchanged
      expect(selected.readOnly).toBe(false)
    })
  })
})
