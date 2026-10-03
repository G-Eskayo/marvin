import { describe, it, expect, vi } from 'vitest'
import { createChangeDetector, issuesEndpoint } from '../webhook-server/gh_watch.js'

const probeFrom = (script) => {
  const calls = []
  const probe = vi.fn(async (repo, etag) => {
    calls.push({ repo, etag })
    return script.shift()
  })
  return { probe, calls }
}

describe('createChangeDetector', () => {
  it('records the first etag silently, then fires only when it changes', async () => {
    const { probe, calls } = probeFrom([{ status: 200, etag: 'a' }, { status: 304 }, { status: 200, etag: 'b' }])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/r'])
    expect(onChange).not.toHaveBeenCalled()
    await d.tick(['o/r'])
    expect(onChange).not.toHaveBeenCalled()
    await d.tick(['o/r'])
    expect(onChange).toHaveBeenCalledWith('o/r')
    expect(calls.map((c) => c.etag)).toEqual([undefined, 'a', 'a'])
  })

  it('tracks each repo separately', async () => {
    const { probe } = probeFrom([{ status: 200, etag: 'x' }, { status: 200, etag: 'y' }, { status: 200, etag: 'x2' }, { status: 304 }])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/a', 'o/b'])
    await d.tick(['o/a', 'o/b'])
    expect(onChange.mock.calls).toEqual([['o/a']])
  })

  it('ignores probe failures and keeps its last etag', async () => {
    const answers = [async () => ({ status: 200, etag: 'a' }), async () => { throw new Error('offline') }, async () => ({ status: 304 })]
    const probe = vi.fn((repo, etag) => answers.shift()(repo, etag))
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/r'])
    await expect(d.tick(['o/r'])).resolves.toBeUndefined()
    await d.tick(['o/r'])
    expect(onChange).not.toHaveBeenCalled()
    expect(probe.mock.calls[2][1]).toBe('a')
  })

  it('forgets repos that left the registry', async () => {
    const { probe } = probeFrom([{ status: 200, etag: 'a' }, { status: 200, etag: 'b' }])
    const onChange = vi.fn()
    const d = createChangeDetector({ probe, onChange })
    await d.tick(['o/r'])
    await d.tick([])
    await d.tick(['o/r']) // re-added: treated as first sight again, not a change
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('issuesEndpoint', () => {
  it('asks for only the most recently updated item, any state', () => {
    expect(issuesEndpoint('o/r')).toBe('https://api.github.com/repos/o/r/issues?state=all&sort=updated&direction=desc&per_page=1')
  })
})
