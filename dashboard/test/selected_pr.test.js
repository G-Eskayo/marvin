import { describe, it, expect, vi } from 'vitest'
import { stillInList, recheckVanished, applyRecheck } from '../src/lib/selected_pr.js'

describe('stillInList: check if PR is still in a list', () => {
  it('returns true when PR is in the list', () => {
    const pr = { url: 'https://github.com/G-Eskayo/marvin/pull/123' }
    const list = [
      { url: 'https://github.com/G-Eskayo/marvin/pull/122' },
      { url: 'https://github.com/G-Eskayo/marvin/pull/123' },
      { url: 'https://github.com/G-Eskayo/marvin/pull/124' }
    ]
    expect(stillInList(pr, list)).toBe(true)
  })

  it('returns false when PR is not in the list', () => {
    const pr = { url: 'https://github.com/G-Eskayo/marvin/pull/999' }
    const list = [
      { url: 'https://github.com/G-Eskayo/marvin/pull/122' },
      { url: 'https://github.com/G-Eskayo/marvin/pull/123' }
    ]
    expect(stillInList(pr, list)).toBe(false)
  })

  it('returns false when PR is null', () => {
    const list = [{ url: 'https://github.com/G-Eskayo/marvin/pull/123' }]
    expect(stillInList(null, list)).toBe(false)
  })

  it('returns false when list is null', () => {
    const pr = { url: 'https://github.com/G-Eskayo/marvin/pull/123' }
    expect(stillInList(pr, null)).toBe(false)
  })

  it('returns false when both are null', () => {
    expect(stillInList(null, null)).toBe(false)
  })

  it('returns false when list is empty', () => {
    const pr = { url: 'https://github.com/G-Eskayo/marvin/pull/123' }
    expect(stillInList(pr, [])).toBe(false)
  })
})

describe('recheckVanished: recheck PR status in history', () => {
  it('returns the PR when state is MERGED', async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/123'
    const historyDetail = vi.fn().mockResolvedValue({
      state: 'MERGED',
      mergedAt: '2026-10-13T18:47:50Z'
    })
    const result = await recheckVanished(url, historyDetail)
    expect(result).toEqual({ state: 'MERGED', mergedAt: '2026-10-13T18:47:50Z' })
    expect(historyDetail).toHaveBeenCalledWith(url)
  })

  it('returns the PR when state is CLOSED', async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/123'
    const historyDetail = vi.fn().mockResolvedValue({
      state: 'CLOSED',
      number: 123
    })
    const result = await recheckVanished(url, historyDetail)
    expect(result).toEqual({ state: 'CLOSED', number: 123 })
  })

  it('returns null when state is OPEN', async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/123'
    const historyDetail = vi.fn().mockResolvedValue({
      state: 'OPEN',
      number: 123
    })
    const result = await recheckVanished(url, historyDetail)
    expect(result).toBeNull()
  })

  it('returns null when historyDetail returns null', async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/123'
    const historyDetail = vi.fn().mockResolvedValue(null)
    const result = await recheckVanished(url, historyDetail)
    expect(result).toBeNull()
  })

  it('returns null when historyDetail rejects', async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/123'
    const historyDetail = vi.fn().mockRejectedValue(new Error('Network error'))
    const result = await recheckVanished(url, historyDetail)
    expect(result).toBeNull()
  })

  it('returns null when url is null', async () => {
    const historyDetail = vi.fn()
    const result = await recheckVanished(null, historyDetail)
    expect(result).toBeNull()
    expect(historyDetail).not.toHaveBeenCalled()
  })

  it('returns null when historyDetail is null', async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/123'
    const result = await recheckVanished(url, null)
    expect(result).toBeNull()
  })

  it('returns a resolved promise (not bare null) when url is null', async () => {
    const historyDetail = vi.fn()
    const result = recheckVanished(null, historyDetail)
    // Verify it's actually a promise, not a bare null
    expect(result).toBeInstanceOf(Promise)
    const awaited = await result
    expect(awaited).toBeNull()
  })

  it('returns a resolved promise (not bare null) when historyDetail is null', async () => {
    const result = recheckVanished('https://example.com', null)
    // Verify it's actually a promise, not a bare null
    expect(result).toBeInstanceOf(Promise)
    const awaited = await result
    expect(awaited).toBeNull()
  })
})

describe('applyRecheck: apply the recheck result to update selected PR', () => {
  it('updates selected PR with fresh data', () => {
    const selected = {
      url: 'https://github.com/G-Eskayo/marvin/pull/123',
      title: 'Fix bug',
      number: 123,
      readOnly: false,
      state: 'OPEN'
    }
    const fresh = {
      state: 'MERGED',
      mergedAt: '2026-10-13T18:47:50Z'
    }
    const result = applyRecheck(selected, null, fresh)
    expect(result).toEqual({
      url: 'https://github.com/G-Eskayo/marvin/pull/123',
      title: 'Fix bug',
      number: 123,
      readOnly: true,
      state: 'MERGED',
      mergedAt: '2026-10-13T18:47:50Z'
    })
  })

  it('sets readOnly to true', () => {
    const selected = { url: 'x', readOnly: false, state: 'OPEN' }
    const fresh = { state: 'MERGED' }
    expect(applyRecheck(selected, null, fresh).readOnly).toBe(true)
  })

  it('preserves original fields when fresh does not have them', () => {
    const selected = {
      url: 'x',
      title: 'Original title',
      number: 123,
      readOnly: false
    }
    const fresh = { state: 'CLOSED' }
    const result = applyRecheck(selected, null, fresh)
    expect(result.title).toBe('Original title')
    expect(result.number).toBe(123)
    expect(result.state).toBe('CLOSED')
  })

  it('returns selected as-is when fresh is null', () => {
    const selected = { url: 'x', readOnly: false, state: 'OPEN' }
    const result = applyRecheck(selected, null, null)
    expect(result).toEqual(selected)
  })

  it('returns selected as-is when selected is null', () => {
    const fresh = { state: 'MERGED' }
    const result = applyRecheck(null, null, fresh)
    expect(result).toBeNull()
  })

  it('handles both null inputs', () => {
    const result = applyRecheck(null, null, null)
    expect(result).toBeNull()
  })

  it('preserves additional fields not in fresh', () => {
    const selected = {
      url: 'x',
      title: 'Test',
      number: 42,
      readOnly: false,
      state: 'OPEN',
      evidence: { verdict: 'pass' },
      images: []
    }
    const fresh = { state: 'MERGED', mergedAt: '2026-10-13T18:47:50Z' }
    const result = applyRecheck(selected, null, fresh)
    expect(result.evidence).toEqual({ verdict: 'pass' })
    expect(result.images).toEqual([])
    expect(result.title).toBe('Test')
  })

  it('returns selected unchanged when selected !== asked (stale recheck protection)', () => {
    const selected = {
      url: 'x',
      title: 'Test',
      number: 42,
      readOnly: false,
      state: 'OPEN'
    }
    const asked = {
      url: 'y',
      title: 'Different',
      number: 43,
      readOnly: false,
      state: 'OPEN'
    }
    const fresh = { state: 'MERGED', mergedAt: '2026-10-13T18:47:50Z' }
    const result = applyRecheck(selected, asked, fresh)
    // Should return selected unchanged because selected !== asked (user selected a different PR)
    expect(result).toBe(selected)
    expect(result.state).toBe('OPEN')
    expect(result.readOnly).toBe(false)
  })

  it('only protects against stale rechecks when asked is provided', () => {
    const selected = {
      url: 'x',
      title: 'Test',
      number: 42,
      readOnly: false,
      state: 'OPEN'
    }
    const fresh = { state: 'MERGED', mergedAt: '2026-10-13T18:47:50Z' }
    // When asked is null, the race check is disabled (backward compat for tests/old code)
    const resultNoAsk = applyRecheck(selected, null, fresh)
    expect(resultNoAsk.state).toBe('MERGED')
    expect(resultNoAsk.readOnly).toBe(true)
    // When asked is defined but selected === asked, apply fresh data normally
    const resultMatching = applyRecheck(selected, selected, fresh)
    expect(resultMatching.state).toBe('MERGED')
    expect(resultMatching.readOnly).toBe(true)
  })
})
