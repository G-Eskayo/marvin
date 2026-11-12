import { describe, it, expect, afterEach } from 'vitest'
import { createServer } from 'http'
import { createMergeServiceTracker } from '../electron/main/merge_service_status.js'
import { listPipelinePrs } from '../electron/main/mr_review.js'

describe('createMergeServiceTracker', () => {
  it('test 1: instant clear on first successful read', () => {
    let now = 0
    const tracker = createMergeServiceTracker({ cacheMs: 30_000, now: () => now })

    now = 0
    tracker.report(true)
    expect(tracker.status().down).toBe(false)
  })

  it('test 2: debounced latch (unreachable becomes down only after cache expires)', () => {
    let now = 0
    const tracker = createMergeServiceTracker({ cacheMs: 30_000, now: () => now })

    now = 0
    tracker.report(false)
    expect(tracker.status().down).toBe(false)

    now = 15_000
    expect(tracker.status().down).toBe(false)

    now = 30_001
    expect(tracker.status().down).toBe(true)
  })

  it('test 9: recovers immediately on a successful read', () => {
    let now = 0
    const tracker = createMergeServiceTracker({ cacheMs: 30_000, now: () => now })

    now = 0
    tracker.report(false)
    now = 30_001
    expect(tracker.status().down).toBe(true)

    now = 30_001
    tracker.report(true)
    expect(tracker.status().down).toBe(false)
  })

  it('test 11: debounce timer starts on first failure and latches after cacheMs', () => {
    let now = 0
    const tracker = createMergeServiceTracker({ cacheMs: 30_000, now: () => now })

    now = 0
    tracker.report(false)
    expect(tracker.status().down).toBe(false)

    now = 25_000
    tracker.report(false)
    expect(tracker.status().down).toBe(false)

    now = 30_001
    expect(tracker.status().down).toBe(true)

    now = 55_001
    expect(tracker.status().down).toBe(true)
  })
})

describe('merge_service_status integration: full path with closed port (case 5, 11)', () => {
  const servers = []
  afterEach(async () => { await Promise.all(servers.splice(0).map((s) => new Promise((r) => s.close(() => r())))) })

  async function closedPortUrl() {
    const s = createServer()
    await new Promise((r) => s.listen(0, '127.0.0.1', r))
    const port = s.address().port
    await new Promise((r) => s.close(r))
    return `http://127.0.0.1:${port}`
  }

  it('case 5: a .json() parse failure returns {} instead of throwing, server answered so report(true)', async () => {
    // Serve invalid JSON to trigger a parse failure; the hardened getter returns {} and reports reachable
    const server = createServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end('not valid json')
    })
    servers.push(server)
    await new Promise((r) => server.listen(0, '127.0.0.1', r))
    const url = `http://127.0.0.1:${server.address().port}`

    const tracker = createMergeServiceTracker()
    // Use the same hardened getter pattern as index.js: on parse failure, return {}, report reachable
    const getRebaseStatus = async () => {
      const res = await fetch(`${url}/rebase-status`, { signal: AbortSignal.timeout(300) })
      if (!res.ok) return {}
      try {
        return await res.json()
      } catch {
        return {}
      }
    }

    const prs = await listPipelinePrs(
      async () => [{
        number: 1,
        title: 'Test',
        url: 'https://github.com/o/r/pull/1',
        body: '## Metrics Comparison\n## Test Results\n## Dev Environment Evidence\nN/A',
        mergeable: 'MERGEABLE',
        statusCheckRollup: [],
        listedAt: Date.now()
      }],
      {
        rebaseStatus: getRebaseStatus,
        mergeServiceTracker: tracker
      }
    )
    // Server answered (200 + parse failure → {}), so the tracker should report reached=true
    expect(tracker.status().down).toBe(false)
    expect(prs[0].mergeServiceDown).toBe(false)
  })

  it('case 11: a genuinely closed port (no connection) is unreachable, reports after debounce', async () => {
    const closedUrl = await closedPortUrl()

    let now = 0
    const tracker = createMergeServiceTracker({ cacheMs: 30_000, now: () => now })

    // Attempt to connect to a closed port; this should fail at the fetch level
    const getRebaseStatus = async () => {
      const res = await fetch(`${closedUrl}/rebase-status`, { signal: AbortSignal.timeout(300) })
      if (!res.ok) return {}
      try {
        return await res.json()
      } catch {
        return {}
      }
    }

    // This fetch will fail (connection refused), so the trackRead in listPipelinePrs
    // will catch it and call report(false)
    now = 0
    const prs = await listPipelinePrs(
      async () => [{
        number: 1,
        title: 'Test',
        url: 'https://github.com/o/r/pull/1',
        body: '## Metrics Comparison\n## Test Results\n## Dev Environment Evidence\nN/A',
        mergeable: 'MERGEABLE',
        statusCheckRollup: [],
        listedAt: Date.now()
      }],
      {
        rebaseStatus: getRebaseStatus,
        mergeServiceTracker: tracker
      }
    )
    // Connection failed, so the tracker reported reached=false
    // But due to the 30s debounce, down should still be false immediately
    expect(tracker.status().down).toBe(false)
    expect(prs[0].mergeServiceDown).toBe(false)

    // After the debounce expires, it should be marked down
    now = 30_001
    expect(tracker.status().down).toBe(true)
  })
})
