import { describe, it, expect } from 'vitest'
import { selectedAfterRefresh } from '../src/lib/selected_after_refresh.js'

describe('selectedAfterRefresh', () => {
  const cur = {
    key: 'pr1',
    url: 'https://github.com/org/repo/pull/1',
    title: 'Test PR',
    number: 1
  }

  it('1. returns "open" when PR is in the fresh list', () => {
    const list = [{ key: 'pr1', url: 'https://github.com/org/repo/pull/1' }]
    expect(selectedAfterRefresh(cur, list, null)).toBe('open')
  })

  it('2. returns "open" when PR is in list even with fetch errors', () => {
    const list = [{ key: 'pr1', url: 'https://github.com/org/repo/pull/1' }]
    expect(selectedAfterRefresh(cur, list, [{ message: 'some error' }])).toBe('open')
  })

  it('3. returns "check" when PR not in list, list fetch succeeded, PR has url', () => {
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    // Empty array means list fetch succeeded with no errors
    expect(selectedAfterRefresh(cur, list, [])).toBe('check')
  })

  it('4. returns "check" when PR not in list with empty errors array', () => {
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    expect(selectedAfterRefresh(cur, list, [])).toBe('check')
  })

  it('5. returns "unknown" when PR not in list but fetch failed', () => {
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    const errors = [{ repo: 'org/repo', message: 'network error' }]
    expect(selectedAfterRefresh(cur, list, errors)).toBe('unknown')
  })

  it('6. returns "unknown" when PR not in list and listStatus rejected (null errors)', () => {
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    // fetchErrors is null when listStatus() rejects — status is unknown
    expect(selectedAfterRefresh(cur, list, null)).toBe('unknown')
  })

  it('7. returns "none" when cur is null', () => {
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    expect(selectedAfterRefresh(null, list, null)).toBe('none')
  })

  it('8. returns "none" when PR not in list and has no url', () => {
    const noPrWithoutUrl = { key: 'pr1', title: 'Test PR' }
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    expect(selectedAfterRefresh(noPrWithoutUrl, list, [])).toBe('none')
  })

  it('9. returns "unknown" when fetch error is for this PR\'s repo', () => {
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    const errors = [{ repo: 'org/repo', message: 'network error' }]
    expect(selectedAfterRefresh(cur, list, errors)).toBe('unknown')
  })

  it('10. returns "check" when fetch error is for different repo', () => {
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    const errors = [{ repo: 'other/repo', message: 'network error' }]
    expect(selectedAfterRefresh(cur, list, errors)).toBe('check')
  })

  it('11. returns "unknown" when fetch error for this repo (extracted from URL)', () => {
    const prWithoutRepo = {
      key: 'pr1',
      url: 'https://github.com/org/repo/pull/1',
      title: 'Test PR'
    }
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    const errors = [{ repo: 'org/repo', message: 'network error' }]
    expect(selectedAfterRefresh(prWithoutRepo, list, errors)).toBe('unknown')
  })

  it('12. returns "check" when fetch error for different repo (extracted from URL)', () => {
    const prWithoutRepo = {
      key: 'pr1',
      url: 'https://github.com/org/repo/pull/1',
      title: 'Test PR'
    }
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    const errors = [{ repo: 'other/org', message: 'network error' }]
    expect(selectedAfterRefresh(prWithoutRepo, list, errors)).toBe('check')
  })

  it('13. returns "none" when PR is readOnly (closed/merged) - prevents repeated checks', () => {
    const closedPr = {
      key: 'pr1',
      url: 'https://github.com/org/repo/pull/1',
      title: 'Test PR',
      readOnly: true
    }
    const list = [{ key: 'pr2', url: 'https://github.com/org/repo/pull/2' }]
    // Even with successful list fetch, readOnly PR returns 'none' (no historyDetail call)
    expect(selectedAfterRefresh(closedPr, list, [])).toBe('none')
  })
})
