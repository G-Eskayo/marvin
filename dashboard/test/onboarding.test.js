import { describe, it, expect, beforeEach, vi } from 'vitest'
import { readOnboardingPlans } from '../electron/main/onboarding'

// Mock fs functions
vi.mock('fs', () => ({
  readFileSync: vi.fn(),
  existsSync: vi.fn()
}))

import { readFileSync, existsSync } from 'fs'

describe('onboarding.js', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns empty array for no boards', () => {
    const result = readOnboardingPlans(null)
    expect(result).toEqual([])
  })

  it('returns empty array for empty boards', () => {
    const result = readOnboardingPlans([])
    expect(result).toEqual([])
  })

  it('handles missing onboarding files with not_planned_yet status', () => {
    existsSync.mockReturnValue(false)
    const boards = [{ repo: 'test/repo' }]
    const result = readOnboardingPlans(boards)

    expect(result).toHaveLength(1)
    expect(result[0]).toEqual({
      repo: 'test/repo',
      generated_at: null,
      pieces: null,
      offers: null,
      status: 'not_planned_yet'
    })
  })

  it('reads and parses valid onboarding plan files', () => {
    const planData = {
      repo: 'test/repo',
      generated_at: '2026-10-06T12:00:00Z',
      pieces: { profile: { state: 'ok', reason: 'exists' } },
      offers: { merge_from_dashboard: true, dispatch: true }
    }

    existsSync.mockReturnValue(true)
    readFileSync.mockReturnValue(JSON.stringify(planData))

    const boards = [{ repo: 'test/repo' }]
    const result = readOnboardingPlans(boards)

    expect(result).toHaveLength(1)
    expect(result[0]).toEqual({
      repo: 'test/repo',
      generated_at: '2026-10-06T12:00:00Z',
      pieces: planData.pieces,
      offers: planData.offers,
      status: 'planned'
    })
  })

  it('handles JSON parse errors with read_error status', () => {
    existsSync.mockReturnValue(true)
    readFileSync.mockReturnValue('invalid json {')

    const boards = [{ repo: 'test/repo' }]
    const result = readOnboardingPlans(boards)

    expect(result).toHaveLength(1)
    expect(result[0]).toEqual({
      repo: 'test/repo',
      generated_at: null,
      pieces: null,
      offers: null,
      status: 'read_error'
    })
  })

  it('extracts repo name correctly from full repo path', () => {
    existsSync.mockReturnValue(false)
    const boards = [
      { repo: 'G-Eskayo/marvin' },
      { repo: 'another-owner/another-repo' }
    ]
    const result = readOnboardingPlans(boards)

    expect(result).toHaveLength(2)
    expect(result[0].repo).toBe('G-Eskayo/marvin')
    expect(result[1].repo).toBe('another-owner/another-repo')
  })

  it('passes through offers from the plan data', () => {
    const planData = {
      repo: 'test/repo',
      generated_at: '2026-10-06T12:00:00Z',
      pieces: { profile: { state: 'ok' } },
      offers: { merge_from_dashboard: false, dispatch: true }
    }

    existsSync.mockReturnValue(true)
    readFileSync.mockReturnValue(JSON.stringify(planData))

    const boards = [{ repo: 'test/repo' }]
    const result = readOnboardingPlans(boards)

    expect(result[0].offers).toEqual(planData.offers)
  })
})

import { withProfileState } from '../electron/main/onboarding.js'

describe('withProfileState', () => {
  it('merges current profile state by repo', () => {
    const plans = [
      { repo: 'o/a', offers: { dispatch: true, merge_from_dashboard: true } },
      { repo: 'o/b', offers: { dispatch: false, merge_from_dashboard: true } }
    ]
    const profiles = [
      { repo: 'o/a', dispatch: 'on', mergeFromDashboard: false },
      { repo: 'o/b', dispatch: 'off', mergeFromDashboard: true }
    ]

    const result = withProfileState(plans, profiles)
    expect(result[0].current).toEqual({ dispatch: 'on', mergeFromDashboard: false })
    expect(result[1].current).toEqual({ dispatch: 'off', mergeFromDashboard: true })
  })

  it('sets current to null when no matching profile exists for a planned repo', () => {
    const plans = [{ repo: 'o/a', offers: { dispatch: true } }]
    const profiles = []

    const result = withProfileState(plans, profiles)
    expect(result[0].current).toBeNull()
  })

  it('does not modify plans without profiles', () => {
    const plans = [{ repo: 'o/a', offers: null, status: 'not_planned_yet' }]
    const profiles = []

    const result = withProfileState(plans, profiles)
    expect(result[0]).toEqual({ ...plans[0], current: null })
  })
})
