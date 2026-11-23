import { describe, it, expect, vi } from 'vitest'
import { ensureWebhooks } from '../webhook-server/gh_webhook_provision.js'

describe('gh_webhook_provision: ensureWebhooks', () => {
  const repos = ['org/repo1', 'org/repo2']
  const url = 'https://example.com/github-webhook'
  const secret = 'test-secret-key'

  describe('case 16: no existing hook for a repo → creates one', () => {
    it('creates a webhook with correct URL, events, and secret', async () => {
      const executed = []
      const exec = async (args) => {
        executed.push(args)
        // Simulate: list returns empty (no hooks exist)
        if (args.includes('--paginate')) return ''
        // Create succeeded
        return 'created'
      }

      await ensureWebhooks({ repos: ['org/newrepo'], url, secret, exec })

      // Should have called: list existing hooks, then create
      expect(executed).toHaveLength(2)
      expect(executed[0]).toContain('repos/org/newrepo/hooks')
      expect(executed[0]).toContain('--paginate')

      const createCmd = executed[1]
      expect(createCmd).toContain('POST')
      // Events must be in array format (-f events[]=push -f events[]=...)
      expect(createCmd).toContain('events[]=push')
      expect(createCmd).toContain('events[]=pull_request')
      expect(createCmd).toContain('events[]=pull_request_review')
      // Config parameters must be nested under config[...]
      expect(createCmd).toContain(`config[url]=${url}`)
      expect(createCmd).toContain('config[content_type]=json')
      expect(createCmd).toContain(`config[secret]=${secret}`)
      expect(createCmd).toContain('config[insecure_ssl]=false')
    })
  })

  describe('case 17: existing hook with wrong URL/events → updates it in place (PATCH)', () => {
    it('patches the hook to match the desired URL and events, never creates duplicate', async () => {
      const executed = []
      const exec = async (args) => {
        executed.push(args)
        // Simulate: list returns multiple hooks, one with correct URL
        if (args.includes('--paginate')) {
          return `${JSON.stringify({ id: 123, url: 'https://old-url/webhook' })}\n${JSON.stringify({ id: 456, url })}`
        }
        // Patch succeeded
        return 'patched'
      }

      await ensureWebhooks({ repos: ['org/repo1'], url, secret, exec })

      // Should list, see the hook exists with correct URL, then PATCH it
      const patchCmd = executed.find((args) => args.includes('PATCH'))
      expect(patchCmd).toBeDefined()
      expect(patchCmd.join(' ')).toContain('456') // hook ID that matches our URL
      expect(patchCmd).toContain('PATCH')
      // Verify PATCH includes all required config fields and events
      expect(patchCmd).toContain('events[]=push')
      expect(patchCmd).toContain(`config[url]=${url}`)
      expect(patchCmd).toContain(`config[secret]=${secret}`)

      // Should NOT have created a new hook (only list + patch)
      const createCmd = executed.find((args) => args.includes('POST') && args[1].includes('repos'))
      expect(createCmd).toBeUndefined()
    })
  })

  describe('case 18: existing hook already correct → still patches to ensure events are correct (idempotent)', () => {
    it('when hook URL matches, patches to ensure events are set', async () => {
      const executed = []
      const exec = async (args) => {
        executed.push(args)
        // Simulate: list returns a hook with correct URL
        if (args.includes('--paginate')) {
          // Return as a JSON line (the actual format)
          return JSON.stringify({ id: 123, url })
        }
        // Patch/create succeeded
        return 'ok'
      }

      await ensureWebhooks({ repos: ['org/repo1'], url, secret, exec })

      // Should list and then patch (to ensure events are correct)
      expect(executed).toHaveLength(2)
      expect(executed[0]).toContain('--paginate')

      const patchCmd = executed[1]
      expect(patchCmd).toContain('PATCH')
      expect(patchCmd.join(' ')).toContain('hooks/123')
      // Events must be in array format
      expect(patchCmd).toContain('events[]=push')
      expect(patchCmd).toContain('events[]=pull_request')
      expect(patchCmd).toContain('events[]=pull_request_review')
      // Config parameters must include the secret
      expect(patchCmd).toContain(`config[secret]=${secret}`)
    })
  })

  describe('case 19: gh exec fails for one repo (rate limit, renamed) → logs error, continues with rest of batch', () => {
    it('one repo failure does not block others; each repo is processed independently', async () => {
      const executed = []
      const logs = []
      const original = console.error
      console.error = (...args) => logs.push(args.join(' '))

      const exec = async (args) => {
        executed.push(args)
        // Check which repo this is for
        if (args.some((a) => a.includes('repo1'))) {
          throw new Error('rate limited: 403')
        }
        // repo2 succeeds
        if (args.includes('--paginate')) return ''
        return 'ok'
      }

      // Should NOT throw, should handle the error gracefully and continue
      let threwError = false
      try {
        await ensureWebhooks({ repos: ['org/repo1', 'org/repo2'], url, secret, exec })
      } catch (e) {
        threwError = true // Error was thrown
      }
      expect(threwError).toBe(false) // No error should be thrown, errors are caught internally

      console.error = original

      // repo1 should have failed and been logged
      expect(logs.some((l) => l.includes('repo1'))).toBe(true)

      // But repo2 should have still been attempted
      const repo2Calls = executed.filter((args) => args.some((a) => a.includes('repo2')))
      expect(repo2Calls.length).toBeGreaterThan(0)
    })

    it('error is logged but processing continues to next repo', async () => {
      const logs = []
      const original = console.error
      console.error = (...args) => logs.push(args.join(' '))

      const executed = []
      const exec = async (args) => {
        executed.push(args)
        if (args.some((a) => a.includes('repo1'))) {
          throw new Error('rate limited')
        }
        if (args.includes('--paginate')) return ''
        return 'ok'
      }

      await ensureWebhooks({ repos: ['org/repo1', 'org/repo2'], url, secret, exec })

      console.error = original
      expect(logs.length).toBeGreaterThan(0)
      expect(logs.some((l) => l.includes('repo1'))).toBe(true)

      // Both repos should have been attempted (repo2 after repo1 failed)
      const repo1Calls = executed.filter((args) => args.some((a) => a.includes('repo1')))
      const repo2Calls = executed.filter((args) => args.some((a) => a.includes('repo2')))
      expect(repo1Calls.length).toBeGreaterThan(0)
      expect(repo2Calls.length).toBeGreaterThan(0)
    })
  })

  describe('parameter validation', () => {
    it('requires exec, url, secret, and repos; throws if any missing', async () => {
      const exec = async () => ''

      await expect(ensureWebhooks({ repos: [], url, secret, exec }))
        .rejects
        .toThrow(/requires/)

      await expect(ensureWebhooks({ repos, url, secret, exec: null }))
        .rejects
        .toThrow(/requires/)

      await expect(ensureWebhooks({ repos, url: '', secret, exec }))
        .rejects
        .toThrow(/requires/)

      await expect(ensureWebhooks({ repos, url, secret: '', exec }))
        .rejects
        .toThrow(/requires/)
    })
  })

  describe('webhook events and configuration', () => {
    it('webhook includes push, pull_request, and pull_request_review events', async () => {
      const executed = []
      const exec = async (args) => {
        executed.push(args)
        if (args.includes('--paginate')) return ''
        return 'ok'
      }

      await ensureWebhooks({ repos: ['org/repo1'], url, secret, exec })

      const createCmd = executed.find((args) => args.includes('POST'))
      expect(createCmd).toBeDefined()
      expect(createCmd).toContain('events[]=push')
      expect(createCmd).toContain('events[]=pull_request')
      expect(createCmd).toContain('events[]=pull_request_review')
    })

    it('webhook is set to active=true and content_type=json', async () => {
      const executed = []
      const exec = async (args) => {
        executed.push(args)
        if (args.includes('--paginate')) return ''
        return 'ok'
      }

      await ensureWebhooks({ repos: ['org/repo1'], url, secret, exec })

      const createCmd = executed.find((args) => args.includes('POST'))
      expect(createCmd.join(' ')).toContain('active=true')
      expect(createCmd).toContain('config[content_type]=json')
    })

    it('webhook is created with the secret in config', async () => {
      const executed = []
      const exec = async (args) => {
        executed.push(args)
        if (args.includes('--paginate')) return ''
        return 'ok'
      }

      await ensureWebhooks({ repos: ['org/repo1'], url, secret, exec })

      const createCmd = executed.find((args) => args.includes('POST'))
      expect(createCmd).toBeDefined()
      expect(createCmd).toContain(`config[secret]=${secret}`)
    })

    it('webhook is patched with the secret in config', async () => {
      const executed = []
      const exec = async (args) => {
        executed.push(args)
        if (args.includes('--paginate')) {
          return JSON.stringify({ id: 456, url })
        }
        return 'ok'
      }

      await ensureWebhooks({ repos: ['org/repo1'], url, secret, exec })

      const patchCmd = executed.find((args) => args.includes('PATCH'))
      expect(patchCmd).toBeDefined()
      expect(patchCmd).toContain(`config[secret]=${secret}`)
    })
  })
})
