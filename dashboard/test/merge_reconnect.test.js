import { describe, it, expect } from 'vitest'
import { checkInflight, followAfterDrop } from '../electron/main/merge_reconnect.js'

const PR = 'https://github.com/G-Eskayo/marvin/pull/559'
const progress = { stages: { fetching: { state: 'running' }, queued: { state: 'done' }, tests: { state: 'waiting' } }, seq: 2 }
const finalResult = { merged: true, reengaged: false, reason: null }

describe('merge_reconnect', () => {
  it('checkInflight fetches inflight data', async () => {
    const mockFetchJson = (url) => {
      expect(url).toContain('/inflight')
      return { inflight: { [PR]: { stage: 'fetching', seq: 2 } } }
    }
    const result = await checkInflight('http://localhost:7878/inflight', { fetchJson: mockFetchJson })
    expect(result.inflight[PR]).toEqual({ stage: 'fetching', seq: 2 })
  })

  it('followAfterDrop: PR is inflight with final result -> followed with result', async () => {
    const testProgress = { stages: { queued: { state: 'done' }, fetching: { state: 'running' }, tests: { state: 'waiting' } }, seq: 2 }
    const mockFetchJson = (url) => {
      if (url.includes('/inflight')) return { inflight: { [PR]: { stage: 'fetching', seq: 2 } } }
      return { merge: { progress: testProgress, result: finalResult } }
    }
    const reconnected = await followAfterDrop({
      url: PR,
      machine: { url: 'http://localhost:7878/approve', id: 'mini', label: 'the Mac mini' },
      mergeOps: {},
      push: () => {},
      fetchJson: mockFetchJson
    })
    expect(reconnected.followed).toBe(true)
    expect(reconnected.progress.seq).toBe(2)
    expect(reconnected.progress.stages).toBeDefined()
    expect(reconnected.result.merged).toBe(true)
  })

  it('followAfterDrop: PR inflight is gone but merge-progress has final result -> followed', async () => {
    const mockFetchJson = (url) => {
      if (url.includes('/inflight')) return { inflight: {} }
      return { merge: { progress, result: finalResult } }
    }
    const result = await followAfterDrop({
      url: PR,
      machine: { url: 'http://localhost:7878/approve', id: 'mini', label: 'the Mac mini' },
      mergeOps: {},
      push: () => {},
      fetchJson: mockFetchJson,
      maxRetries: 1
    })
    expect(result.followed).toBe(true)
    expect(result.result).toEqual(finalResult)
  })

  it('followAfterDrop: polls until merge completes', async () => {
    let pollCount = 0
    const mockFetchJson = (url) => {
      pollCount += 1
      if (url.includes('/inflight')) return { inflight: { [PR]: { stage: 'fetching', seq: 2 } } }
      // First two calls: still running, no result yet
      if (pollCount <= 2) return { merge: { progress } }
      // Third call: merge finished
      return { merge: { progress, result: finalResult } }
    }
    const result = await followAfterDrop({
      url: PR,
      machine: { url: 'http://localhost:7878/approve', id: 'mini', label: 'the Mac mini' },
      mergeOps: {},
      push: () => {},
      pollMs: 1,
      maxRetries: 10,
      sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
      fetchJson: mockFetchJson
    })
    expect(result.followed).toBe(true)
    expect(result.result).toEqual(finalResult)
    expect(pollCount).toBeGreaterThan(2)
  })

  it('followAfterDrop: PR is not inflight and no result -> not followed', async () => {
    const mockFetchJson = () => ({ inflight: {}, merge: { progress } })
    const result = await followAfterDrop({
      url: PR,
      machine: { url: 'http://localhost:7878/approve', id: 'mini', label: 'the Mac mini' },
      mergeOps: {},
      push: () => {},
      fetchJson: mockFetchJson,
      maxRetries: 1
    })
    expect(result.followed).toBe(false)
    expect(result.reason).toContain('no longer running')
  })

  it('followAfterDrop: retries on error up to maxRetries', async () => {
    let attempt = 0
    const mockFetchJson = (url) => {
      attempt += 1
      if (attempt < 3) throw new Error('Network error')
      if (url.includes('/inflight')) return { inflight: { [PR]: { stage: 'fetching', seq: 2 } } }
      return { merge: { progress, result: finalResult } }
    }
    const result = await followAfterDrop({
      url: PR,
      machine: { url: 'http://localhost:7878/approve', id: 'mini', label: 'the Mac mini' },
      mergeOps: {},
      push: () => {},
      pollMs: 5,
      maxRetries: 3,
      sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
      fetchJson: mockFetchJson
    })
    expect(attempt).toBeGreaterThanOrEqual(3)
    expect(result.followed).toBe(true)
  })

  it('followAfterDrop: exhausts retries and returns error reason', async () => {
    const mockFetchJson = () => {
      throw new Error('Webhook unreachable')
    }
    const result = await followAfterDrop({
      url: PR,
      machine: { url: 'http://localhost:7878/approve', id: 'mini', label: 'the Mac mini' },
      mergeOps: {},
      push: () => {},
      pollMs: 1,
      maxRetries: 2,
      sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
      fetchJson: mockFetchJson
    })
    expect(result.followed).toBe(false)
    expect(result.reason).toContain('Could not reconnect')
    expect(result.reason).toContain('Webhook unreachable')
  })
})
