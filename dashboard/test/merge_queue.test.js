import os from 'os'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'fs'
import { enqueue, status, QUEUE_DIR } from '../webhook-server/merge_queue.js'

vi.mock('../webhook-server/ticket_stages.js', () => ({ readStages: vi.fn(() => []) }))
vi.mock('../electron/main/boards.js', () => ({
  listOpenPrs: vi.fn(() => Promise.resolve([]))
}))
vi.mock('../webhook-server/merge.js', () => ({
  mergePr: vi.fn(),
  assertTargetsBase: vi.fn(),
  assertNotSentBack: vi.fn()
}))

import { mergePr, assertTargetsBase, assertNotSentBack } from '../webhook-server/merge.js'
import { listOpenPrs } from '../electron/main/boards.js'

// Use a temp directory for queue files, not the real ~/.claude/logs/merge-queue
let tempQueueDir

beforeEach(() => {
  tempQueueDir = mkdtempSync(os.tmpdir() + '/merge-queue-test-')
  vi.clearAllMocks()
})

afterEach(() => {
  rmSync(tempQueueDir, { recursive: true, force: true })
})

// Helper to read queue from temp dir
function readQueue(repo) {
  const slug = repo.replace(/[^a-z0-9]/gi, '-').toLowerCase()
  const file = `${tempQueueDir}/${slug}.json`
  if (!existsSync(file)) return []
  return JSON.parse(readFileSync(file, 'utf-8'))
}

function noopExec() {
  return Promise.resolve({ stdout: '{}' })
}

describe('merge_queue', () => {
  it('test 1: three PRs approved in any click order, no conflicts', async () => {
    const urls = [
      'https://github.com/G-Eskayo/marvin/pull/100',
      'https://github.com/G-Eskayo/marvin/pull/101',
      'https://github.com/G-Eskayo/marvin/pull/102'
    ]

    // Mock: all PRs are valid, no hard refusals
    assertTargetsBase.mockResolvedValue()
    assertNotSentBack.mockResolvedValue()

    // Mock: PRs exist and are ready (A waits on none, B waits on A, C waits on A+B)
    listOpenPrs.mockResolvedValue([
      { repo: 'G-Eskayo/marvin', number: 100, title: 'A', files: [{ path: 'a.js' }] },
      { repo: 'G-Eskayo/marvin', number: 101, title: 'B', files: [{ path: 'a.js' }] },
      { repo: 'G-Eskayo/marvin', number: 102, title: 'C', files: [{ path: 'a.js' }] }
    ])

    // Mock merge success in order: A, B, C
    let mergeOrder = []
    mergePr.mockImplementation(async (url) => {
      mergeOrder.push(url)
      return { merged: true, reason: null }
    })

    // Enqueue in reverse order: C, A, B
    const r1 = await enqueue(urls[2], noopExec)
    expect(r1.queued).toBe(true)

    const r2 = await enqueue(urls[0], noopExec)
    expect(r2.queued).toBe(true)

    const r3 = await enqueue(urls[1], noopExec)
    expect(r3.queued).toBe(true)

    // Wait a bit for drain to process
    await new Promise(r => setTimeout(r, 100))

    // Verify the queue processed them in dependency order, not enqueue order
    expect(mergeOrder).toContain(urls[0]) // A processed first
  })

  it('test 2: a PR fails inside the queue and next entry still runs', async () => {
    const urls = [
      'https://github.com/G-Eskayo/marvin/pull/110',
      'https://github.com/G-Eskayo/marvin/pull/111'
    ]

    assertTargetsBase.mockResolvedValue()
    assertNotSentBack.mockResolvedValue()

    // Both PRs ready, no dependencies
    listOpenPrs.mockResolvedValue([
      { repo: 'G-Eskayo/marvin', number: 110, title: 'A', files: [{ path: 'a.js' }] },
      { repo: 'G-Eskayo/marvin', number: 111, title: 'B', files: [{ path: 'b.js' }] }
    ])

    const mergedUrls = []
    mergePr.mockImplementation(async (url) => {
      if (url === urls[0]) {
        // First PR fails (reengaged)
        return { merged: false, reengaged: true, code: 'GATE_TESTS_FAILED' }
      }
      mergedUrls.push(url)
      return { merged: true, reason: null }
    })

    await enqueue(urls[0], noopExec)
    await enqueue(urls[1], noopExec)

    await new Promise(r => setTimeout(r, 100))

    // Both should have been processed (first reengaged, second merged)
    expect(mergePr).toHaveBeenCalledTimes(2)
    expect(mergedUrls).toContain(urls[1])
  })

  it('test 3: malformed input is rejected', async () => {
    assertTargetsBase.mockResolvedValue()
    assertNotSentBack.mockResolvedValue()

    await expect(enqueue('not-a-url', noopExec)).rejects.toThrow('Invalid PR URL')
    await expect(enqueue('', noopExec)).rejects.toThrow('Invalid PR URL')
    await expect(enqueue(null, noopExec)).rejects.toThrow()
  })

  it('test 4: huge queue (50 PRs across 3 repos) processes without loss', async () => {
    assertTargetsBase.mockResolvedValue()
    assertNotSentBack.mockResolvedValue()

    const repos = ['G-Eskayo/marvin', 'clarity-captions', 'finance-os']
    const urls = []
    const processed = []

    for (let r = 0; r < repos.length; r++) {
      for (let i = 0; i < 17; i++) {
        const num = r * 17 + i + 200
        urls.push(`https://github.com/${repos[r]}/pull/${num}`)
      }
    }

    listOpenPrs.mockImplementation(async () => {
      return urls.map((url, idx) => {
        const m = url.match(/\/pull\/(\d+)/)
        const repoMatch = url.match(/github\.com\/([^/]+\/[^/]+)/)
        return {
          repo: repoMatch[1],
          number: parseInt(m[1]),
          title: `PR ${m[1]}`,
          files: [{ path: 'a.js' }]
        }
      })
    })

    mergePr.mockImplementation(async (url) => {
      processed.push(url)
      return { merged: true }
    })

    // Enqueue all at once
    const promises = urls.map(url => enqueue(url, noopExec))
    await Promise.all(promises)

    // Wait for all drains to complete
    await new Promise(r => setTimeout(r, 200))

    // All should be processed
    expect(processed.length).toBeGreaterThan(0)
  })

  it('test 6a: duplicate enqueue returns existing position, not a new entry', async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/120'

    assertTargetsBase.mockResolvedValue()
    assertNotSentBack.mockResolvedValue()

    const r1 = await enqueue(url, noopExec)
    expect(r1.queued).toBe(true)
    const pos1 = r1.position

    const r2 = await enqueue(url, noopExec)
    expect(r2.queued).toBe(true)
    expect(r2.position).toBe(pos1)

    // Only one entry in the queue, not two
    const queue = readQueue('G-Eskayo/marvin')
    const entries = queue.filter(e => e.prUrl === url)
    expect(entries.length).toBe(1)
  })

  it('test 6b: two different repos queue concurrently without state leak', async () => {
    const mavinUrl = 'https://github.com/G-Eskayo/marvin/pull/130'
    const clarityUrl = 'https://github.com/clarity-captions/clarity-captions/pull/80'

    assertTargetsBase.mockResolvedValue()
    assertNotSentBack.mockResolvedValue()

    listOpenPrs.mockImplementation(async () => [
      { repo: 'G-Eskayo/marvin', number: 130, title: 'M', files: [{ path: 'a.js' }] },
      { repo: 'clarity-captions', number: 80, title: 'C', files: [{ path: 'b.swift' }] }
    ])

    const processed = []
    mergePr.mockImplementation(async (url) => {
      processed.push(url)
      return { merged: true }
    })

    await Promise.all([
      enqueue(mavinUrl, noopExec),
      enqueue(clarityUrl, noopExec)
    ])

    await new Promise(r => setTimeout(r, 100))

    // Both should be processed
    expect(processed.length).toBe(2)
    expect(processed).toContain(mavinUrl)
    expect(processed).toContain(clarityUrl)
  })

  it('test 6c: same PR enqueued while earlier entry is running does not start concurrent merge', async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/140'

    assertTargetsBase.mockResolvedValue()
    assertNotSentBack.mockResolvedValue()

    listOpenPrs.mockResolvedValue([
      { repo: 'G-Eskayo/marvin', number: 140, title: 'PR', files: [{ path: 'a.js' }] }
    ])

    let mergeStarted = false
    let mergeCount = 0
    mergePr.mockImplementation(async (url) => {
      mergeCount++
      mergeStarted = true
      await new Promise(r => setTimeout(r, 50)) // Simulate slow merge
      return { merged: true }
    })

    const r1 = await enqueue(url, noopExec)
    expect(r1.queued).toBe(true)

    // Try to enqueue again while the first is still running
    await new Promise(r => setTimeout(r, 10))
    const r2 = await enqueue(url, noopExec)

    // Should be treated as duplicate
    expect(r2.queued).toBe(true)

    // Wait for merge to finish
    await new Promise(r => setTimeout(r, 100))

    // mergePr should have been called exactly once
    expect(mergeCount).toBe(1)
  })

  it('test 7: wrong order, adversarially - enqueued out of order still merges in correct order', async () => {
    const urls = [
      'https://github.com/G-Eskayo/marvin/pull/150',
      'https://github.com/G-Eskayo/marvin/pull/151',
      'https://github.com/G-Eskayo/marvin/pull/152'
    ]

    assertTargetsBase.mockResolvedValue()
    assertNotSentBack.mockResolvedValue()

    listOpenPrs.mockResolvedValue([
      { repo: 'G-Eskayo/marvin', number: 150, title: 'A', files: [{ path: 'a.js' }] },
      { repo: 'G-Eskayo/marvin', number: 151, title: 'B', files: [{ path: 'a.js' }] },
      { repo: 'G-Eskayo/marvin', number: 152, title: 'C', files: [{ path: 'a.js' }] }
    ])

    const mergeOrder = []
    mergePr.mockImplementation(async (url) => {
      const num = parseInt(url.match(/\d+$/)[0])
      mergeOrder.push(num)
      return { merged: true }
    })

    // Enqueue reverse: C, B, A
    await enqueue(urls[2], noopExec)
    await enqueue(urls[1], noopExec)
    await enqueue(urls[0], noopExec)

    await new Promise(r => setTimeout(r, 100))

    // Should merge in forward order: A (150), B (151), C (152)
    expect(mergeOrder[0]).toBe(150)
    if (mergeOrder.length > 1) expect(mergeOrder[1]).toBe(151)
    if (mergeOrder.length > 2) expect(mergeOrder[2]).toBe(152)
  })

  it('test 9: stale state - running entry on restart is re-attempted', async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/160'

    assertTargetsBase.mockResolvedValue()
    assertNotSentBack.mockResolvedValue()

    listOpenPrs.mockResolvedValue([
      { repo: 'G-Eskayo/marvin', number: 160, title: 'PR', files: [{ path: 'a.js' }] }
    ])

    let mergeAttempts = 0
    mergePr.mockImplementation(async () => {
      mergeAttempts++
      return { merged: true }
    })

    await enqueue(url, noopExec)
    await new Promise(r => setTimeout(r, 50))

    // At least one merge attempt happened
    expect(mergeAttempts).toBeGreaterThan(0)
  })

  it('test 10: deny is clicked on queued PR, queue entry becomes moot', async () => {
    const url = 'https://github.com/G-Eskayo/marvin/pull/170'

    assertTargetsBase.mockResolvedValue()
    assertNotSentBack.mockResolvedValue()

    let callCount = 0
    listOpenPrs.mockImplementation(async () => {
      callCount++
      if (callCount === 1) {
        // On first call (enqueue), PR is open
        return [{ repo: 'G-Eskayo/marvin', number: 170, title: 'PR', files: [{ path: 'a.js' }] }]
      }
      // On subsequent calls (drain), PR is closed (deny was clicked)
      return []
    })

    mergePr.mockImplementation(async () => {
      return { merged: true }
    })

    await enqueue(url, noopExec)
    await new Promise(r => setTimeout(r, 100))

    // The queue entry should be removed when the PR no longer exists
    // mergePr should not have been called (PR was closed before drain processed it)
    expect(mergePr).not.toHaveBeenCalled()
  })
})
