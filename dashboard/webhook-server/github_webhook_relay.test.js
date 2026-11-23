import { describe, it, expect, vi } from 'vitest'
import { relayGithubChange, handleGithubChangeRequest } from './github_webhook_relay.js'

describe('github_webhook_relay', () => {
  describe('relayGithubChange', () => {
    it('posts to all peers', async () => {
      const post = vi.fn().mockResolvedValue({})
      const peers = [
        { host: '192.168.1.100' },
        { host: '192.168.1.101' }
      ]
      await relayGithubChange({ repo: 'test/repo', peers, post })
      expect(post).toHaveBeenCalledTimes(2)
      expect(post).toHaveBeenCalledWith(
        'http://192.168.1.100:7878/github-change',
        { repo: 'test/repo' },
        expect.any(Object)
      )
    })

    it('handles no peers gracefully', async () => {
      const post = vi.fn()
      await relayGithubChange({ repo: 'test/repo', peers: [], post })
      expect(post).not.toHaveBeenCalled()
    })

    it('continues if some posts fail', async () => {
      const post = vi.fn()
      post.mockRejectedValueOnce(new Error('failed'))
      post.mockResolvedValueOnce({})
      const peers = [
        { host: '192.168.1.100' },
        { host: '192.168.1.101' }
      ]
      await relayGithubChange({ repo: 'test/repo', peers, post })
      expect(post).toHaveBeenCalledTimes(2)
    })
  })

  describe('handleGithubChangeRequest', () => {
    const makeRequest = (overrides = {}) => ({
      method: 'POST',
      url: '/github-change',
      headers: {},
      body: JSON.stringify({ repo: 'test/repo' }),
      remoteAddress: '127.0.0.1',
      ...overrides
    })

    it('rejects when remote address is not allowed', () => {
      const req = makeRequest({ remoteAddress: '10.0.0.1' })
      const onChange = vi.fn()
      const { status } = handleGithubChangeRequest(req, {
        onChange,
        allowedPeerFn: () => false
      })
      expect(status).toBe(403)
      expect(onChange).not.toHaveBeenCalled()
    })

    it('rejects invalid JSON body', () => {
      const req = makeRequest({ body: 'not json' })
      const onChange = vi.fn()
      const { status } = handleGithubChangeRequest(req, {
        onChange,
        allowedPeerFn: () => true
      })
      expect(status).toBe(400)
      expect(onChange).not.toHaveBeenCalled()
    })

    it('rejects when repo is missing', () => {
      const req = makeRequest({ body: JSON.stringify({}) })
      const onChange = vi.fn()
      const { status } = handleGithubChangeRequest(req, {
        onChange,
        allowedPeerFn: () => true
      })
      expect(status).toBe(400)
      expect(onChange).not.toHaveBeenCalled()
    })

    it('accepts valid request and calls onChange', () => {
      const req = makeRequest()
      const onChange = vi.fn()
      const { status, body } = handleGithubChangeRequest(req, {
        onChange,
        allowedPeerFn: () => true,
        watchedRepos: () => ['test/repo']
      })
      expect(status).toBe(200)
      expect(JSON.parse(body).ok).toBe(true)
      expect(onChange).toHaveBeenCalledWith('test/repo')
    })

    it('uses default allowedPeerFn', () => {
      const req = makeRequest({ remoteAddress: '127.0.0.1' })
      const onChange = vi.fn()
      const { status } = handleGithubChangeRequest(req, {
        onChange,
        watchedRepos: () => ['test/repo']
      })
      // localhost should be allowed by default
      expect(status).toBe(200)
      expect(onChange).toHaveBeenCalledWith('test/repo')
    })

    it('rejects repo not in watched repos', () => {
      const req = makeRequest({ body: JSON.stringify({ repo: 'unknown/repo' }) })
      const onChange = vi.fn()
      const { status } = handleGithubChangeRequest(req, {
        onChange,
        allowedPeerFn: () => true,
        watchedRepos: () => ['test/repo', 'other/repo']
      })
      expect(status).toBe(403)
      expect(onChange).not.toHaveBeenCalled()
    })

    it('accepts repo in watched repos', () => {
      const req = makeRequest()
      const onChange = vi.fn()
      const { status } = handleGithubChangeRequest(req, {
        onChange,
        allowedPeerFn: () => true,
        watchedRepos: () => ['test/repo', 'other/repo']
      })
      expect(status).toBe(200)
      expect(onChange).toHaveBeenCalledWith('test/repo')
    })
  })
})
