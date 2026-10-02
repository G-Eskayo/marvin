import { describe, it, expect } from 'vitest'
import { loadGhToken } from '../webhook-server/gh_auth.js'

// The webhook's `gh pr merge` / `git push --force-with-lease` relied on each
// machine's OWN `gh auth login`. On 2026-10-02 the laptop's login was found
// expired ("The token in default is invalid"), so every Approve routed to the
// laptop's webhook failed with nothing surfacing why. The pipeline already uses
// one credential file (~/.claude/.gh-token, materialised on both machines);
// the webhook now reads the same source so a stale per-machine login can't
// silently break merges.

const read = (map) => (p) => {
  if (!(p in map)) throw Object.assign(new Error('ENOENT'), { code: 'ENOENT' })
  return map[p]
}

describe('loadGhToken', () => {
  it('sets GH_TOKEN from ~/.claude/.gh-token, trimming whitespace and newlines', () => {
    const env = {}
    const source = loadGhToken(env, '/home/u', read({ '/home/u/.claude/.gh-token': 'gho_abc123\n' }))
    expect(env.GH_TOKEN).toBe('gho_abc123')
    expect(source).toBe('file')
  })

  it('never overrides a GH_TOKEN that is already set explicitly', () => {
    const env = { GH_TOKEN: 'explicit' }
    const source = loadGhToken(env, '/home/u', read({ '/home/u/.claude/.gh-token': 'from-file' }))
    expect(env.GH_TOKEN).toBe('explicit')
    expect(source).toBe('env')
  })

  it('leaves the environment untouched when the file is missing, so gh falls back to its own login', () => {
    const env = {}
    const source = loadGhToken(env, '/home/u', read({}))
    expect('GH_TOKEN' in env).toBe(false)
    expect(source).toBe('none')
  })

  it('ignores an empty or whitespace-only token file rather than exporting a blank credential', () => {
    const env = {}
    const source = loadGhToken(env, '/home/u', read({ '/home/u/.claude/.gh-token': '  \n' }))
    expect('GH_TOKEN' in env).toBe(false)
    expect(source).toBe('none')
  })

  it('never returns or logs the token value itself', () => {
    const env = {}
    const source = loadGhToken(env, '/home/u', read({ '/home/u/.claude/.gh-token': 'gho_secret' }))
    expect(String(source)).not.toContain('gho_secret')
  })
})
