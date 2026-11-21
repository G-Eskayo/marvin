import { describe, it, expect, vi } from 'vitest'
import { createPeerCopies } from '../electron/main/peer_copy.js'
import { readStamped } from '../electron/main/stamped.js'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { join } from 'path'
import { tmpdir } from 'os'

const tmp = () => mkdtempSync(join(tmpdir(), 'peer-copy-feed-'))

describe('GitHub feed peer read integration (consumers via peer_copy)', () => {
  it('prefers a fresh producer copy over a stale local copy', async () => {
    const d = tmp()
    try {
      const localPath = join(d, 'feed.json')

      // Write a stale local feed (generated 11 minutes ago)
      const now = Date.now()
      const staledFeed = {
        version: 1,
        host: 'mac-mini-1',
        generated_at: new Date(now - 11 * 60_000).toISOString(),
        alive_at: now - 11 * 60_000,
        tolerance_s: 600,
        repos: { 'owner/repo': { prs: { at: now, value: [] } } }
      }
      writeFileSync(localPath, JSON.stringify(staledFeed))

      // Producer copy is fresh (just made)
      const freshProducerFeed = {
        version: 1,
        host: 'mac-mini-2012',
        generated_at: new Date(now).toISOString(),
        alive_at: now,
        tolerance_s: 600,
        repos: { 'owner/repo': { prs: { at: now, value: [{ number: 42 }] } } }
      }

      // Create peer copies that will return the fresh feed
      const peerCopies = createPeerCopies({
        isProducer: () => false,
        producerHost: () => 'producer-host',
        fetchCopy: vi.fn(async () => freshProducerFeed),
        now: () => now
      })

      // Read the feed through peer_copy
      const result = await peerCopies.read('github-feed', localPath, { defaultToleranceS: 600 })

      // Should prefer the fresh producer copy
      expect(result.from).toBe('producer')
      expect(result.value.repos['owner/repo'].prs.value).toEqual([{ number: 42 }])
      expect(result.ageS).toBe(0)
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('falls back to local copy when producer is unreachable', async () => {
    const d = tmp()
    try {
      const localPath = join(d, 'feed.json')
      const now = Date.now()

      // Local feed is stale (older than tolerance)
      const localFeed = {
        version: 1,
        host: 'mac-mini-1',
        generated_at: new Date(now - 11 * 60_000).toISOString(),
        alive_at: now - 11 * 60_000,
        tolerance_s: 600,
        repos: { 'owner/repo': { prs: { at: now, value: [{ number: 1 }] } } }
      }
      writeFileSync(localPath, JSON.stringify(localFeed))

      // Producer is unreachable
      const peerCopies = createPeerCopies({
        isProducer: () => false,
        producerHost: () => 'producer-host',
        fetchCopy: vi.fn(async () => null),
        now: () => now
      })

      // Should return local copy when producer is unreachable
      const result = await peerCopies.read('github-feed', localPath, { defaultToleranceS: 600 })

      expect(result.from).toBe('local')
      expect(result.producerUnreachable).toBe(true)
      expect(result.value.repos['owner/repo'].prs.value).toEqual([{ number: 1 }])
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })

  it('producer does not fetch when it is the primary host', async () => {
    const d = tmp()
    try {
      const localPath = join(d, 'feed.json')
      const now = Date.now()

      // Fresh local feed (just made)
      const freshLocalFeed = {
        version: 1,
        host: 'mac-mini-1',
        generated_at: new Date(now).toISOString(),
        alive_at: now,
        tolerance_s: 600,
        repos: { 'owner/repo': { prs: { at: now, value: [{ number: 99 }] } } }
      }
      writeFileSync(localPath, JSON.stringify(freshLocalFeed))

      const fetchCopy = vi.fn()
      const peerCopies = createPeerCopies({
        isProducer: () => true,
        producerHost: () => 'self',
        fetchCopy,
        now: () => now
      })

      // When this is the producer, should not fetch from peer
      const result = await peerCopies.read('github-feed', localPath, { defaultToleranceS: 600 })

      expect(result.from).toBe('local')
      expect(result.ageS).toBe(0)
      expect(fetchCopy).not.toHaveBeenCalled()
    } finally {
      rmSync(d, { recursive: true, force: true })
    }
  })
})
