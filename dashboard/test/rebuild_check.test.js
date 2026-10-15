import { describe, it, expect } from 'vitest'
import { createRebuildCheckTrigger, REBUILD_CHECK_ARGS } from '../webhook-server/rebuild_check.js'

// #443: merges made on GitHub never reached the installed app, because only the dashboard's own Approve & Merge
// triggered a rebuild. The change watch sees every merge on G-Eskayo/marvin within seconds; it now starts the rebuild
// check (lib/dashboard_rebuild.py decides whether the app is actually behind, and never runs two builds at once).

function fakeSpawn() {
  const calls = []
  const spawn = (cmd, args, opts) => { calls.push({ cmd, args, opts }); return { unref() { calls.at(-1).unref = true } } }
  return { calls, spawn }
}

describe('createRebuildCheckTrigger', () => {
  it('a change on G-Eskayo/marvin starts the rebuild check, detached so a restart of this server cannot kill it', () => {
    const { calls, spawn } = fakeSpawn()
    const trigger = createRebuildCheckTrigger({ spawn, now: () => 0 })
    expect(trigger('G-Eskayo/marvin')).toBe(true)
    expect(calls).toHaveLength(1)
    expect(calls[0].args).toEqual(REBUILD_CHECK_ARGS)
    expect(calls[0].opts).toMatchObject({ detached: true, stdio: 'ignore' })
    expect(calls[0].unref).toBe(true)
  })

  it('changes on other repos (clarity-captions, portfolio...) never touch the dashboard app', () => {
    const { calls, spawn } = fakeSpawn()
    const trigger = createRebuildCheckTrigger({ spawn, now: () => 0 })
    for (const repo of ['G-Eskayo/clarity-captions', 'G-Eskayo/marvin-mobile', 'someone/marvin', '', undefined]) expect(trigger(repo)).toBe(false)
    expect(calls).toHaveLength(0)
  })

  it('a burst of change pings (a merge is several GitHub events) starts one check, then again after the quiet period', () => {
    const { calls, spawn } = fakeSpawn()
    let t = 0
    const trigger = createRebuildCheckTrigger({ spawn, now: () => t, minGapMs: 60_000 })
    trigger('G-Eskayo/marvin'); t = 20_000; trigger('G-Eskayo/marvin'); t = 40_000; trigger('G-Eskayo/marvin')
    expect(calls).toHaveLength(1)
    t = 70_000; trigger('G-Eskayo/marvin')
    expect(calls).toHaveLength(2)
  })

  it('a check that cannot start (missing python, spawn error) is swallowed: the watch keeps running', () => {
    const trigger = createRebuildCheckTrigger({ spawn: () => { throw new Error('ENOENT') }, now: () => 0 })
    expect(() => trigger('G-Eskayo/marvin')).not.toThrow()
  })

  it('runs the venv interpreter on lib/dashboard_rebuild.py (bare python3 lacks the job_events deps)', () => {
    expect(REBUILD_CHECK_ARGS.at(-1)).toMatch(/\.agents\/lib\/dashboard_rebuild\.py$/)
  })
})
