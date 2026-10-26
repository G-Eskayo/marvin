import { describe, it, expect } from 'vitest'
import { supportRepos, createSupportSync } from '../webhook-server/support_sync.js'

describe('support sync in the webhook server (ADR 0073)', () => {
  it('reads the support repos from the instance, and an unreadable instance is none', () => {
    expect(supportRepos(() => JSON.stringify({ support: { watch: ['a/marvin-support'] } }))).toEqual(['a/marvin-support'])
    expect(supportRepos(() => '{broken')).toEqual([])
    expect(supportRepos(() => { throw new Error('ENOENT') })).toEqual([])
  })

  it('a burst of changes runs one sync and then exactly one more', () => {
    const pending = []
    const sync = createSupportSync({ run: (_py, args, _o, cb) => pending.push({ args, cb }), log: () => {} })
    sync('a'); sync('b'); sync('c'); sync('d')
    expect(pending).toHaveLength(1)
    expect(pending[0].args.slice(1)).toEqual(['sync', '--attempt'])
    pending[0].cb(null, '{"ok": true}')
    expect(pending).toHaveLength(2)
    pending[1].cb(null, '{"ok": true}')
    expect(pending).toHaveLength(2)
  })

  it('a failed sync does not stop the next one', () => {
    const pending = []
    const sync = createSupportSync({ run: (_py, _a, _o, cb) => pending.push(cb), log: () => {} })
    sync('a')
    pending[0](new Error('gh down'), '')
    sync('b')
    expect(pending).toHaveLength(2)
  })
})

import { supportWatcher, startAppSupportWatch } from '../webhook-server/support_sync.js'

describe('who watches the support repos', () => {
  it('the helper’s always-on webhook server, the helped person’s open dashboard, and nobody without support', () => {
    expect(supportWatcher('helper')).toBe('webhook')
    expect(supportWatcher('helped')).toBe('app')
    expect(supportWatcher(null)).toBe(null)
  })

  it('the app watch syncs at start, authenticates with the person’s token, and syncs on each change', () => {
    const synced = []
    let watch
    let probeEnv
    startAppSupportWatch({
      repos: () => ['a/marvin-support'],
      token: 'tok',
      sync: (source) => synced.push(source),
      createGithubProbe: (env) => { probeEnv = env; return 'probe' },
      startChangeWatch: (opts) => { watch = opts }
    })
    expect(synced).toEqual(['app start'])
    expect(probeEnv).toEqual({ GH_TOKEN: 'tok' })
    expect(watch.getRepos()).toEqual(['a/marvin-support'])
    watch.ping('a/marvin-support')
    expect(synced).toEqual(['app start', 'a/marvin-support'])
  })
})
