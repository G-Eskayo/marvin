import { describe, it, expect } from 'vitest'
import { createWebhookRestartCheckTrigger, WEBHOOK_RESTART_CHECK_ARGS } from '../webhook-server/rebuild_check.js'

// Webhook restart check: triggered when a code change is detected (marvin merge on any path), similar to rebuild_check.
// lib/webhook_restart.py makes the actual decision (is the server behind origin/main, settled, not restarting,
// not failed on the same code, merge not in flight); this only wakes it.

function fakeSpawn() {
  const calls = []
  const spawn = (cmd, args, opts) => { calls.push({ cmd, args, opts }); return { unref() { calls.at(-1).unref = true } } }
  return { calls, spawn }
}

describe('createWebhookRestartCheckTrigger', () => {
  it('a change on G-Eskayo/marvin starts the webhook restart check, detached so a restart of this server cannot kill it', () => {
    const { calls, spawn } = fakeSpawn()
    const trigger = createWebhookRestartCheckTrigger({ spawn, now: () => 0 })
    expect(trigger('G-Eskayo/marvin')).toBe(true)
    expect(calls).toHaveLength(1)
    expect(calls[0].args).toEqual(WEBHOOK_RESTART_CHECK_ARGS)
    expect(calls[0].opts).toMatchObject({ detached: true, stdio: 'ignore' })
    expect(calls[0].unref).toBe(true)
  })

  it('changes on other repos never trigger the webhook restart check', () => {
    const { calls, spawn } = fakeSpawn()
    const trigger = createWebhookRestartCheckTrigger({ spawn, now: () => 0 })
    for (const repo of ['G-Eskayo/clarity-captions', 'G-Eskayo/marvin-mobile', 'someone/marvin', '', undefined]) expect(trigger(repo)).toBe(false)
    expect(calls).toHaveLength(0)
  })

  it('a burst of change pings starts one check, then again after the quiet period', () => {
    const { calls, spawn } = fakeSpawn()
    let t = 0
    const trigger = createWebhookRestartCheckTrigger({ spawn, now: () => t, minGapMs: 60_000 })
    trigger('G-Eskayo/marvin'); t = 20_000; trigger('G-Eskayo/marvin'); t = 40_000; trigger('G-Eskayo/marvin')
    expect(calls).toHaveLength(1)
    t = 70_000; trigger('G-Eskayo/marvin')
    expect(calls).toHaveLength(2)
  })

  it('a check that cannot start (missing python, spawn error) is swallowed: the watch keeps running', () => {
    const trigger = createWebhookRestartCheckTrigger({ spawn: () => { throw new Error('ENOENT') }, now: () => 0 })
    expect(() => trigger('G-Eskayo/marvin')).not.toThrow()
  })

  it('runs the venv interpreter on lib/webhook_restart.py (bare python3 lacks the job_events deps)', () => {
    expect(WEBHOOK_RESTART_CHECK_ARGS.at(-1)).toMatch(/\.agents\/lib\/webhook_restart\.py$/)
  })

  it('deferred trigger with minGapMs: 0 can retry immediately after merge finishes (no shared debounce)', () => {
    const { calls, spawn } = fakeSpawn()
    let t = 0
    // Simulates: ping with 60s debounce sees merge in flight (debounce consumed)
    const trigger = createWebhookRestartCheckTrigger({ spawn, now: () => t, minGapMs: 60_000 })
    trigger('G-Eskayo/marvin'); t = 20_000; trigger('G-Eskayo/marvin')  // debounce blocks second call
    expect(calls).toHaveLength(1)

    // afterRun with minGapMs: 0 can retry immediately (no debounce)
    const deferredTrigger = createWebhookRestartCheckTrigger({ spawn, now: () => t, minGapMs: 0 })
    deferredTrigger('G-Eskayo/marvin')
    expect(calls).toHaveLength(2)
  })
})
