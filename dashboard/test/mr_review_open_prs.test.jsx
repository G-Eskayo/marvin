import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { OpenPrs } from '../src/components/MrReview.jsx'

describe('OpenPrs with saved state', () => {
  let prevWindow
  let prevApi
  let prevLocalStorage
  let mockApi = null

  beforeEach(() => {
    prevWindow = global.window
    prevApi = global.window?.api
    prevLocalStorage = global.window?.localStorage
    if (!global.window) global.window = {}
    mockApi = {
      mr: {
        list: vi.fn(),
        parity: vi.fn(),
        autoMergeReport: vi.fn(),
        listStatus: vi.fn(),
        markSeen: vi.fn(),
        onRefresh: vi.fn(() => () => {})
      }
    }
    global.window.api = mockApi
  })

  afterEach(() => {
    // Restore the exact pre-test state of global.window
    if (prevWindow === undefined) {
      delete global.window
    } else {
      if (prevApi !== undefined) global.window.api = prevApi
      else if (global.window) delete global.window.api
      if (prevLocalStorage !== undefined) global.window.localStorage = prevLocalStorage
      else if (global.window) delete global.window.localStorage
    }
  })

  it('renders PR list immediately with valid saved state, without waiting for mr.list() to resolve', () => {
    const now = Date.now()
    const savedPrs = [
      { key: 'pr:1', number: 1, title: 'Test PR', repo: 'G-Eskayo/marvin', url: 'https://github.com/G-Eskayo/marvin/pull/1', hasSchema: false, rawBody: 'Description' }
    ]
    const fakeStorage = {
      getItem: () => JSON.stringify({ at: now, value: savedPrs })
    }
    const prevStorage = global.window?.localStorage
    try {
      global.window.localStorage = fakeStorage
      const html = renderToStaticMarkup(<OpenPrs onCount={() => {}} />)
      expect(html).toContain('Test PR')
      expect(html).not.toContain('Loading')
    } finally {
      if (prevStorage !== undefined) global.window.localStorage = prevStorage
      else if (global.window) delete global.window.localStorage
    }
  })

  it('renders loading state when there is no saved state', () => {
    const fakeStorage = {
      getItem: () => null
    }
    const prevStorage = global.window?.localStorage
    try {
      global.window.localStorage = fakeStorage
      const html = renderToStaticMarkup(<OpenPrs onCount={() => {}} />)
      expect(html).toContain('Loading')
    } finally {
      if (prevStorage !== undefined) global.window.localStorage = prevStorage
      else if (global.window) delete global.window.localStorage
    }
  })

  it('falls back to loading state with corrupted saved state', () => {
    const fakeStorage = {
      getItem: () => 'not valid json {'
    }
    const prevStorage = global.window?.localStorage
    try {
      global.window.localStorage = fakeStorage
      const html = renderToStaticMarkup(<OpenPrs onCount={() => {}} />)
      expect(html).toContain('Loading')
    } finally {
      if (prevStorage !== undefined) global.window.localStorage = prevStorage
      else if (global.window) delete global.window.localStorage
    }
  })

  it('validates shape: falls back to loading if saved.value is not an array', () => {
    const now = Date.now()
    const fakeStorage = {
      getItem: () => JSON.stringify({ at: now, value: { pr: 'not-an-array' } })
    }
    const prevStorage = global.window?.localStorage
    try {
      global.window.localStorage = fakeStorage
      const html = renderToStaticMarkup(<OpenPrs onCount={() => {}} />)
      expect(html).toContain('Loading')
    } finally {
      if (prevStorage !== undefined) global.window.localStorage = prevStorage
      else if (global.window) delete global.window.localStorage
    }
  })

  it('test order independence: globals do not leak between tests', () => {
    // This test runs after others that modified global.window
    // Verify that a fresh render still works (window.api should be set up by beforeEach)
    const html = renderToStaticMarkup(<OpenPrs onCount={() => {}} />)
    expect(html).toContain('Loading')
    // Verify the mock API is available (set by beforeEach)
    expect(mockApi.mr.list).toBeDefined()
  })
})
