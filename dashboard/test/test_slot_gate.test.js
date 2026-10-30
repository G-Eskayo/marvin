import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { _defaultRunTests, pytestParallelArgs, holdTestSlot, withMergeMark } from '../webhook-server/merge.js'
import { vitestIsHeavy, takeSlotForVitest } from '../webhook-server/test_slot.js'

// marvin#940: the merge gate's tests go through this machine's one test slot (lib/test_slot.py), first in line, and
// size their workers to free memory instead of the core count. The holder is a real process on a real lock in a temp
// directory; the gate's commands are fakes.
let dir, saved
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'test-slot-gate-'))
  saved = { d: process.env.MARVIN_TEST_SLOT_DIR, h: process.env.MARVIN_TEST_SLOT }
  process.env.MARVIN_TEST_SLOT_DIR = dir
  delete process.env.MARVIN_TEST_SLOT
})
afterEach(() => {
  for (const [k, v] of [['MARVIN_TEST_SLOT_DIR', saved.d], ['MARVIN_TEST_SLOT', saved.h]]) {
    if (v === undefined) delete process.env[k]
    else process.env[k] = v
  }
  rmSync(dir, { recursive: true, force: true })
})

const cache = { seed: async () => {}, store: async () => {} }

describe('the gate runs its tests in the slot, merges first', () => {
  // Since marvin#826 every check goes through .github/run-check.sh <id>; `--affected` calls only ask whether to install.
  const isRun = (cmd, args) => cmd === 'bash' && args[0] === '.github/run-check.sh' && args[2] !== '--affected'

  it('holds the slot as a merge around every check run, and every run knows it is held (their own checks pass through)', async () => {
    const order = []
    const hold = vi.fn(async (args) => { order.push(['hold', ...args]); return { held: true, release: async () => { order.push('release') } } })
    const exec = vi.fn(async (cmd, args, opts) => {
      if (isRun(cmd, args)) order.push([args[1], opts?.env?.MARVIN_TEST_SLOT])
      return { stdout: '', stderr: '' }
    })
    await _defaultRunTests('/repo', exec, undefined, async () => ['-n', '3'], cache, null, hold)
    expect(order[0]).toEqual(['hold', 'hold', '--merge', '--what', 'merge gate'])
    expect(order.at(-1)).toBe('release')
    const runs = order.slice(1, -1)
    expect(runs.map((r) => r[0])).toEqual(expect.arrayContaining(['python', 'dashboard']))
    expect(runs.every((r) => r[1] === 'merge gate')).toBe(true)
  })

  it('releases the slot when a run fails', async () => {
    const release = vi.fn(async () => {})
    const exec = vi.fn(async (cmd, args) => { if (isRun(cmd, args) && args[1] === 'python') throw new Error('2 failed'); return { stdout: '' } })
    await expect(_defaultRunTests('/repo', exec, undefined, async () => [], cache, null, async () => ({ held: true, release }))).rejects.toThrow('2 failed')
    expect(release).toHaveBeenCalledOnce()
  })

  it('both runners get the memory-sized worker count; with -n auto or serial they keep their own default', async () => {
    for (const [par, want] of [[['-n', '3'], '3'], [['-n', 'auto'], undefined], [[], undefined]]) {
      const envs = []
      const exec = vi.fn(async (cmd, args, opts) => { if (isRun(cmd, args)) envs.push(opts?.env?.MARVIN_TEST_WORKERS); return { stdout: '' } })
      await _defaultRunTests('/repo', exec, undefined, async () => par, cache, null, async () => ({ held: false, release: async () => {} }))
      expect(envs.length).toBeGreaterThan(0)
      expect(envs.every((w) => w === want)).toBe(true)
    }
  })

  it('a worker count left in the environment from elsewhere never leaks into a run that asked for auto', async () => {
    const saved = process.env.MARVIN_TEST_WORKERS
    process.env.MARVIN_TEST_WORKERS = '9'
    try {
      const envs = []
      const exec = vi.fn(async (cmd, args, opts) => { if (isRun(cmd, args)) envs.push(opts?.env?.MARVIN_TEST_WORKERS); return { stdout: '' } })
      await _defaultRunTests('/repo', exec, undefined, async () => ['-n', 'auto'], cache, null, async () => ({ held: false, release: async () => {} }))
      expect(envs.every((w) => w === undefined)).toBe(true)
    } finally {
      if (saved === undefined) delete process.env.MARVIN_TEST_WORKERS
      else process.env.MARVIN_TEST_WORKERS = saved
    }
  })

  it('pytestParallelArgs asks test_slot.py how many workers fit in free memory', async () => {
    const run = vi.fn(async (py, args) => ({ stdout: args[1] === 'workers' ? '3\n' : '' }))
    expect(await pytestParallelArgs('/venv/python', run, vi.fn(), '/lib/test_slot.py')).toEqual(['-n', '3'])
    expect(run).toHaveBeenCalledWith('/venv/python', ['/lib/test_slot.py', 'workers'])
  })

  it('an unreadable worker count falls back to -n auto, never to no tests', async () => {
    const run = vi.fn(async (py, args) => { if (args[1] === 'workers') throw new Error('no'); return { stdout: '' } })
    expect(await pytestParallelArgs('/venv/python', run, vi.fn(), '/lib/test_slot.py')).toEqual(['-n', 'auto'])
  })
})

describe('holdTestSlot: a real holder on a real lock', () => {
  it('resolves once the slot is held, records who holds it, and lets go on release', async () => {
    // The repo's venv may not exist in a worktree; any python 3 runs test_slot.py (stdlib only).
    const h = await holdTestSlot(['hold', '--merge', '--what', 'merge gate'], { python: 'python3' })
    expect(h.held).toBe(true)
    expect(JSON.parse(readFileSync(path.join(dir, 'holder.json'), 'utf8')).what).toBe('merge gate')
    await h.release()
    expect(existsSync(path.join(dir, 'holder.json'))).toBe(false)
  }, 15_000)

  it('a holder that cannot start never blocks the merge', async () => {
    const h = await holdTestSlot(['hold'], { python: path.join(dir, 'no-such-python') })
    expect(h.held).toBe(false)
    await h.release()
  })

  it('inside a held slot nothing is spawned', async () => {
    process.env.MARVIN_TEST_SLOT = 'outer'
    const spawnFn = vi.fn()
    const h = await holdTestSlot(['hold'], { spawnFn })
    expect(h.held).toBe(false)
    expect(spawnFn).not.toHaveBeenCalled()
  })
})

describe('a whole vitest run takes the slot (vitest.config.js), one file never waits', () => {
  it.each([
    [['node', 'vitest', 'run'], true],
    [['node', 'vitest'], true],
    [['node', 'vitest', 'run', '--maxWorkers=3'], true],
    [['node', 'vitest', 'run', 'test/merge.test.js'], false],
    [['node', 'vitest', 'run', 'merge'], false]
  ])('%j heavy: %s', (argv, heavy) => {
    expect(vitestIsHeavy(argv)).toBe(heavy)
  })

  it('takeSlotForVitest holds it for a whole run and marks the environment either way, so no test queues on it', async () => {
    const hold = vi.fn(async () => ({ held: true, release: async () => {} }))
    await takeSlotForVitest(['node', 'vitest', 'run'], { hold })
    expect(hold).toHaveBeenCalledWith(['hold', '--what', 'vitest (dashboard)'], expect.objectContaining({ unref: true }))
    expect(process.env.MARVIN_TEST_SLOT).toBe('vitest (dashboard)')
    delete process.env.MARVIN_TEST_SLOT
    const small = vi.fn()
    await takeSlotForVitest(['node', 'vitest', 'run', 'test/x.test.js'], { hold: small })
    expect(small).not.toHaveBeenCalled()
    expect(process.env.MARVIN_TEST_SLOT).toBe('vitest (small run, not queued)')
  })
})

describe('withMergeMark: a merge is marked from the Approve to its end, then the queue is kicked (marvin#940 part 2)', () => {
  it('holds the mark while the merge runs, lets go before the kick, and returns the merge result', async () => {
    const order = []
    const hold = vi.fn(async (args) => { order.push(args.join(' ')); return { held: true, release: async () => { order.push('release') } } })
    const r = await withMergeMark(async () => { order.push('merge'); return { merged: true } }, { hold, kick: () => order.push('kick') })
    expect(r).toEqual({ merged: true })
    expect(order).toEqual(['hold-merge', 'merge', 'release', 'kick'])
  })

  it('a failing merge is still unmarked and kicked, and its error comes through', async () => {
    const order = []
    const hold = async () => ({ held: true, release: async () => { order.push('release') } })
    await expect(withMergeMark(async () => { throw new Error('gate failed') }, { hold, kick: () => order.push('kick') })).rejects.toThrow('gate failed')
    expect(order).toEqual(['release', 'kick'])
  })

  it('a real marker: helpers see the merge while it runs and not after', async () => {
    const { execFileSync } = await import('child_process')
    const pending = () => JSON.parse(execFileSync('python3', [path.join(import.meta.dirname, '..', '..', 'lib', 'test_slot.py'), 'status'], { env: { ...process.env } }).toString()).merge_pending
    const hold = (args) => holdTestSlot(args, { python: 'python3' })
    let during
    await withMergeMark(async () => { during = pending() }, { hold, kick: () => {} })
    expect(during).toBe(true)
    expect(pending()).toBe(false)
  }, 15_000)
})
