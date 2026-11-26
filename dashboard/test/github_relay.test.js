import { describe, it, expect } from 'vitest'
import { relayGithubChange, receiveGithubRelay } from '../webhook-server/github_relay.js'

describe('relayGithubChange', () => {
  it('posts to each peer', async () => {
    const posted = []
    const post = async (url, body) => {
      posted.push({ url, body })
      return { ok: true }
    }
    await relayGithubChange({
      peers: [
        { host: 'mac-mini', port: 7878 },
        { host: 'macbook', port: 7878 }
      ],
      repo: 'owner/repo',
      event: 'pull_request',
      post
    })
    expect(posted).toHaveLength(2)
    expect(posted[0].url).toContain('mac-mini')
    expect(posted[1].url).toContain('macbook')
  })

  it('sends the repo and event in the body', async () => {
    const posted = []
    const post = async (url, body) => {
      posted.push(body)
      return { ok: true }
    }
    await relayGithubChange({
      peers: [{ host: 'peer1' }],
      repo: 'owner/repo',
      event: 'pull_request',
      post
    })
    expect(posted[0]).toEqual({ repo: 'owner/repo', event: 'pull_request' })
  })

  it('fire-and-forget: returns before all posts settle', async () => {
    const slow = new Promise((r) => setTimeout(r, 100))
    const post = async () => slow
    const start = Date.now()
    await relayGithubChange({
      peers: [{ host: 'peer' }],
      repo: 'owner/repo',
      event: 'push',
      post
    })
    const elapsed = Date.now() - start
    expect(elapsed).toBeLessThan(50)
  })

  it('handles post failures gracefully', async () => {
    const post = async () => { throw new Error('offline') }
    await expect(relayGithubChange({
      peers: [{ host: 'peer' }],
      repo: 'owner/repo',
      event: 'push',
      post
    })).resolves.toBeUndefined()
  })

  it('handles empty peer list', async () => {
    const post = async () => { throw new Error('must not post') }
    await relayGithubChange({
      peers: [],
      repo: 'owner/repo',
      event: 'push',
      post
    })
  })
})

describe('receiveGithubRelay', () => {
  it('validates and returns repo and event', () => {
    const result = receiveGithubRelay({ repo: 'owner/repo', event: 'pull_request' })
    expect(result).toEqual({ repo: 'owner/repo', event: 'pull_request' })
  })

  it('returns null on missing repo', () => {
    expect(receiveGithubRelay({ event: 'pull_request' })).toBeNull()
  })

  it('returns null on missing event', () => {
    expect(receiveGithubRelay({ repo: 'owner/repo' })).toBeNull()
  })

  it('returns null on non-string repo or event', () => {
    expect(receiveGithubRelay({ repo: 123, event: 'pull_request' })).toBeNull()
    expect(receiveGithubRelay({ repo: 'owner/repo', event: ['pull_request'] })).toBeNull()
  })

  it('returns null on null body', () => {
    expect(receiveGithubRelay(null)).toBeNull()
  })

  it('returns null on non-object body', () => {
    expect(receiveGithubRelay('invalid')).toBeNull()
  })
})
