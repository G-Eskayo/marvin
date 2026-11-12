import { describe, it, expect, beforeEach, vi } from 'vitest'
import { homedir } from 'node:os'
import path from 'node:path'
import { createCodeSyncCheckTrigger } from '../webhook-server/code_sync_check.js'

// marvin#1195: restart the webhook-server when its code changes. The trigger pulls
// ~/.agents and, on success, starts webhook_restart.py. Failures are logged and swallowed.

const VENV_PYTHON = path.join(homedir(), '.agents', 'venv', 'bin', 'python')
const CODE_SYNC_SCRIPT = path.join(homedir(), '.agents', 'lib', 'code_sync.py')
const WEBHOOK_RESTART_SCRIPT = path.join(homedir(), '.agents', 'lib', 'webhook_restart.py')

function fakeSpawn() {
  const calls = []
  const spawn = (cmd, args, opts) => { calls.push({ cmd, args, opts, type: 'spawn' }); return { unref() { calls.at(-1).unref = true } } }
  return { calls, spawn }
}

function fakeExec(shouldFail = false) {
  const calls = []
  const exec = async (cmd, args) => {
    calls.push({ cmd, args, type: 'exec' })
    if (shouldFail) throw new Error('code-sync: conflict or lock')
  }
  return { calls, exec }
}

describe('createCodeSyncCheckTrigger', () => {
  it('a change on G-Eskayo/marvin runs code_sync pull, and on success spawns webhook_restart detached', async () => {
    const { calls: spawnCalls, spawn } = fakeSpawn()
    const { calls: execCalls, exec } = fakeExec()
    const trigger = createCodeSyncCheckTrigger({ spawn, exec, now: () => 0 })
    const result = await trigger('G-Eskayo/marvin')
    expect(result).toBe(true)
    expect(execCalls).toHaveLength(1)
    expect(execCalls[0].cmd).toBe(VENV_PYTHON)
    expect(execCalls[0].args).toEqual([CODE_SYNC_SCRIPT, 'pull', path.join(homedir(), '.agents')])
    expect(spawnCalls.length).toBeGreaterThanOrEqual(1)
    expect(spawnCalls[0].cmd).toBe(VENV_PYTHON)
    expect(spawnCalls[0].args).toEqual([WEBHOOK_RESTART_SCRIPT])
    expect(spawnCalls[0].opts).toMatchObject({ detached: true, stdio: 'ignore' })
    expect(spawnCalls[0].unref).toBe(true)
  })

  it('changes on other repos never touch it; exec/spawn are never called', async () => {
    const { calls: spawnCalls, spawn } = fakeSpawn()
    const { calls: execCalls, exec } = fakeExec()
    const trigger = createCodeSyncCheckTrigger({ spawn, exec, now: () => 0 })
    for (const repo of ['G-Eskayo/clarity-captions', 'G-Eskayo/marvin-mobile', 'someone/marvin', '', undefined]) {
      expect(await trigger(repo)).toBe(false)
    }
    expect(spawnCalls).toHaveLength(0)
    expect(execCalls).toHaveLength(0)
  })

  it('a burst of pings runs the pull once, then again after the quiet period', async () => {
    const { calls: spawnCalls, spawn } = fakeSpawn()
    const { calls: execCalls, exec } = fakeExec()
    let t = 0
    const trigger = createCodeSyncCheckTrigger({ spawn, exec, now: () => t, minGapMs: 60_000 })
    await trigger('G-Eskayo/marvin'); t = 20_000; await trigger('G-Eskayo/marvin'); t = 40_000; await trigger('G-Eskayo/marvin')
    expect(execCalls).toHaveLength(1)
    expect(spawnCalls.length).toBeGreaterThanOrEqual(1) // at least one initial spawn, may have delayed spawns scheduled
    t = 70_000; await trigger('G-Eskayo/marvin')
    expect(execCalls).toHaveLength(2)
    expect(spawnCalls.length).toBeGreaterThanOrEqual(2) // more spawns including initial and delayed
  })

  it('when code_sync pull fails (conflict/lock), webhook_restart is never spawned and the trigger does not throw', async () => {
    const { calls: spawnCalls, spawn } = fakeSpawn()
    const { calls: execCalls, exec } = fakeExec(true)
    const trigger = createCodeSyncCheckTrigger({ spawn, exec, now: () => 0 })
    const result = await trigger('G-Eskayo/marvin')
    expect(result).toBe(false)
    expect(execCalls).toHaveLength(1)
    expect(spawnCalls).toHaveLength(0)
  })

  it('when spawn throws synchronously (ENOENT, EAGAIN), it is swallowed and the trigger does not throw', async () => {
    const { calls: execCalls, exec } = fakeExec()
    const spawnThatThrows = (cmd, args, opts) => { throw new Error('ENOENT') }
    const trigger = createCodeSyncCheckTrigger({ spawn: spawnThatThrows, exec, now: () => 0 })
    let threwError = false
    try {
      const result = await trigger('G-Eskayo/marvin')
      expect(result).toBe(false)
    } catch {
      threwError = true
    }
    expect(threwError).toBe(false)
    expect(execCalls).toHaveLength(1)
  })

  it('runs the venv interpreter on code_sync.py pull and webhook_restart.py with bare paths', async () => {
    const { calls: spawnCalls, spawn } = fakeSpawn()
    const { calls: execCalls, exec } = fakeExec()
    const trigger = createCodeSyncCheckTrigger({ spawn, exec, now: () => 0 })
    await trigger('G-Eskayo/marvin')
    expect(execCalls[0].cmd).toMatch(/\.agents\/venv\/bin\/python$/)
    expect(execCalls[0].args[0]).toMatch(/\.agents\/lib\/code_sync\.py$/)
    expect(spawnCalls[0].cmd).toMatch(/\.agents\/venv\/bin\/python$/)
    expect(spawnCalls[0].args[0]).toMatch(/\.agents\/lib\/webhook_restart\.py$/)
  })

  it('schedules a delayed re-run of webhook_restart after SETTLE_SECONDS', async () => {
    vi.useFakeTimers()
    try {
      const { calls: spawnCalls, spawn } = fakeSpawn()
      const { calls: execCalls, exec } = fakeExec()
      const trigger = createCodeSyncCheckTrigger({ spawn, exec, now: () => 0 })
      await trigger('G-Eskayo/marvin')
      // Initial spawn should happen immediately
      expect(spawnCalls).toHaveLength(1)
      expect(spawnCalls[0].args[0]).toMatch(/webhook_restart\.py$/)
      // Advance time by 60 seconds (SETTLE_SECONDS)
      await vi.advanceTimersByTimeAsync(60_000)
      // Delayed spawn should now be scheduled
      expect(spawnCalls).toHaveLength(2)
      expect(spawnCalls[1].args[0]).toMatch(/webhook_restart\.py$/)
    } finally {
      vi.useRealTimers()
    }
  })

  it('delayed webhook_restart is spawned detached even if the initial one failed', async () => {
    vi.useFakeTimers()
    try {
      const { calls: spawnCalls, spawn } = fakeSpawn()
      const { calls: execCalls, exec } = fakeExec()
      const trigger = createCodeSyncCheckTrigger({ spawn, exec, now: () => 0 })
      await trigger('G-Eskayo/marvin')
      expect(spawnCalls).toHaveLength(1)
      await vi.advanceTimersByTimeAsync(60_000)
      expect(spawnCalls).toHaveLength(2)
      expect(spawnCalls[1].opts).toMatchObject({ detached: true, stdio: 'ignore' })
      expect(spawnCalls[1].unref).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('delayed webhook_restart spawn errors are caught and logged, not thrown', async () => {
    vi.useFakeTimers()
    try {
      const { calls: execCalls, exec } = fakeExec()
      const spawnThatThrows = () => { throw new Error('ENOENT') }
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const trigger = createCodeSyncCheckTrigger({ spawn: spawnThatThrows, exec, now: () => 0 })
      let threwError = false
      try {
        await trigger('G-Eskayo/marvin')
      } catch {
        threwError = true
      }
      expect(threwError).toBe(false)
      // Advance past the delayed spawn
      await vi.advanceTimersByTimeAsync(60_000)
      // Should have logged both the initial spawn error and the delayed spawn error
      expect(consoleSpy).toHaveBeenCalledWith(expect.stringContaining('[code-sync-check] could not start webhook-restart'))
      expect(consoleSpy).toHaveBeenCalledWith(expect.stringContaining('[code-sync-check] delayed webhook-restart failed'))
      consoleSpy.mockRestore()
    } finally {
      vi.useRealTimers()
    }
  })
})
