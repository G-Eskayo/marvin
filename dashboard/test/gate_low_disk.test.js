import { describe, it, expect, vi } from 'vitest'
import { mergePr, rebaseAndRetest, runDiskFirstAid, MIN_GATE_FREE_BYTES, DISK_FIRST_AID_STEP } from '../webhook-server/merge.js'
import { summarizeGateFailure } from '../webhook-server/failure.js'

vi.mock('../webhook-server/ticket_stages.js', () => ({ recordStage: vi.fn() }))

// 2026-10-28: Approve on two PRs was refused within 3-4 s at "rebasing" with the generic GATE_INFRA line while the Mac
// mini had 1.6 GB free; macOS's aerial wallpaper had refilled the disk since the daily sweep. Now the gate first runs the
// cleanup sweep's own rebuildable trims once (a registered first-aid step), measures again, and goes on when there is
// room. When it still refuses, the message names the disk and both numbers.

const GB = 1024 ** 3
const LOW = 1.6 * GB
const PLENTY = 8 * GB
const freeSeq = (...values) => {
  const fn = vi.fn()
  for (const v of values) fn.mockImplementationOnce(typeof v === 'function' ? v : async () => v)
  fn.mockImplementation(async () => values[values.length - 1])
  return fn
}
const gitFails = () => vi.fn().mockRejectedValue(Object.assign(new Error('stop here'), { stderr: 'stop here' }))

describe('rebaseAndRetest: first aid before refusing on a nearly full disk', () => {
  it('runs first aid once, measures again, and carries on when there is now room', async () => {
    const firstAid = vi.fn(async () => ({ ok: true, changed: true, detail: 'freed 6400 MiB (aerial videos 6400 MiB, caches 0 MiB)' }))
    const progress = vi.fn()
    const exec = gitFails() // reaching git at all proves the gate went on
    await expect(rebaseAndRetest('feature', exec, '/nowhere', vi.fn(), 'main', null, null, progress, freeSeq(LOW, PLENTY), firstAid))
      .rejects.toThrow('stop here')
    expect(firstAid).toHaveBeenCalledTimes(1)
    expect(exec).toHaveBeenCalled()
    const said = progress.mock.calls.map(([, , extra]) => extra?.detail || '').join('\n')
    expect(said).toMatch(/disk nearly full \(1\.6 GB free\)/)
    expect(said).toMatch(/freed 6400 MiB/)
    expect(said).toMatch(/8\.0 GB free now/)
    // logged, not only shown: the tracker writes logDetail lines to the webhook log
    expect(progress.mock.calls.filter(([, , extra]) => extra?.logDetail).length).toBeGreaterThanOrEqual(2)
  })

  it('refuses when still short, says first aid ran, and quotes the space measured AFTER it', async () => {
    const firstAid = vi.fn(async () => ({ ok: true, changed: true, detail: 'freed 300 MiB (aerial videos 300 MiB, caches 0 MiB)' }))
    const exec = vi.fn()
    const result = await rebaseAndRetest('feature', exec, '/nowhere', vi.fn(), 'main', null, null, undefined, freeSeq(LOW, 1.9 * GB), firstAid)
    expect(result.ok).toBe(false)
    expect(exec).not.toHaveBeenCalled()
    expect(firstAid).toHaveBeenCalledTimes(1) // once per approve, never a loop
    const s = summarizeGateFailure(result.reason, { where: 'Mac mini' })
    expect(s.code).toBe('GATE_INFRA')
    expect(s.cause).toBe("The Mac mini's disk is nearly full (1.9 GB free, the check needs 5.0 GB)")
    expect(s.next).toMatch(/cleared rebuildable files first \(freed 300 MiB/i)
  })

  it('a first aid that throws, hangs up with garbage or reports failure is a refusal, never a crash', async () => {
    for (const aid of [
      async () => { throw new Error('python missing') },
      async () => null,
      async () => 'not an object',
      async () => ({ ok: false, changed: false, detail: 'the cleanup sweep is already running on this Mac' })
    ]) {
      const exec = vi.fn()
      const result = await rebaseAndRetest('feature', exec, '/nowhere', vi.fn(), 'main', null, null, undefined, freeSeq(LOW, LOW), vi.fn(aid))
      expect(result.ok).toBe(false)
      expect(exec).not.toHaveBeenCalled()
      expect(summarizeGateFailure(result.reason).cause).toMatch(/disk is nearly full \(1\.6 GB free/)
    }
  })

  it('never runs first aid when there is room', async () => {
    const firstAid = vi.fn()
    await expect(rebaseAndRetest('feature', gitFails(), '/nowhere', vi.fn(), 'main', null, null, undefined, freeSeq(PLENTY), firstAid)).rejects.toThrow()
    expect(firstAid).not.toHaveBeenCalled()
  })

  it('never runs first aid when the free space cannot be read (fails open, as before)', async () => {
    const firstAid = vi.fn()
    await expect(rebaseAndRetest('feature', gitFails(), '/nowhere', vi.fn(), 'main', null, null, undefined, async () => { throw new Error('statfs') }, firstAid)).rejects.toThrow()
    expect(firstAid).not.toHaveBeenCalled()
  })

  it('without a first-aid step (direct callers, older wiring) refuses exactly as before', async () => {
    const result = await rebaseAndRetest('feature', vi.fn(), '/nowhere', vi.fn(), 'main', null, null, undefined, async () => LOW)
    expect(result.ok).toBe(false)
    expect(result.reason).not.toMatch(/first aid/i)
  })

  it('exactly at the floor is enough; one byte under is not', async () => {
    const aid = vi.fn(async () => ({ ok: true, changed: false, detail: 'nothing to clear' }))
    await expect(rebaseAndRetest('f', gitFails(), '/n', vi.fn(), 'main', null, null, undefined, freeSeq(MIN_GATE_FREE_BYTES), aid)).rejects.toThrow('stop here')
    expect(aid).not.toHaveBeenCalled()
    const r = await rebaseAndRetest('f', vi.fn(), '/n', vi.fn(), 'main', null, null, undefined, freeSeq(MIN_GATE_FREE_BYTES - 1, MIN_GATE_FREE_BYTES - 1), aid)
    expect(r.ok).toBe(false)
    expect(aid).toHaveBeenCalledTimes(1)
  })
})

describe('mergePr: the refusal that reaches the dashboard and the log names the cause', () => {
  const PR = 'https://github.com/G-Eskayo/marvin/pull/600'
  const gate = () => vi.fn().mockResolvedValue({ gate: true, headRefName: 'pipeline/x', body: 'Closes G-Eskayo/marvin#147' })
  const exec = () => vi.fn(async () => ({ stdout: JSON.stringify({ baseRefName: 'main', statusCheckRollup: [] }), stderr: '' }))
  const DISK = 'Disk check before rebasing onto main:\n\nNo space left on device for the check: 1.6 GB free, the gate needs 5.0 GB. Free up space on this Mac, then approve again.'

  it('says "The Mac mini\'s disk is nearly full (1.6 GB free, the check needs 5.0 GB)" in the message, stage and remediation', async () => {
    const recordStageFn = vi.fn()
    const reengage = vi.fn()
    const rebase = vi.fn().mockResolvedValue({ ok: false, reason: DISK })
    const err = await mergePr(PR, exec(), () => {}, () => {}, gate(), rebase, reengage, recordStageFn,
      { loadNow: () => ({ id: 'mac-mini-1', load: 1, cores: 4, busy: false }) }).catch((e) => e)
    expect(err.payload.code).toBe('GATE_INFRA')
    expect(err.payload.message).toMatch(/^The Mac mini's disk is nearly full \(1\.6 GB free, the check needs 5\.0 GB\)/)
    expect(err.payload.message).not.toMatch(/build machine or the project's test setup failed/)
    expect(err.payload.remediation).toMatch(/Free up space on this Mac/)
    expect(err.payload.remediation).toMatch(/not sent back/)
    expect(err.payload.remediation).not.toMatch(/What failed|Last output/) // the cause says it; no raw dump
    const gateFail = recordStageFn.mock.calls.find(([, s, st]) => s === 'gate' && st === 'failed')
    expect(gateFail[3]).toMatch(/^GATE_INFRA: The Mac mini's disk is nearly full \(1\.6 GB free/)
    expect(reengage).not.toHaveBeenCalled()
  })

  it('a GATE_INFRA failure with no sentence yet keeps the raw output for a person', async () => {
    const rebase = vi.fn().mockResolvedValue({ ok: false, reason: 'Tests failed after rebasing onto main:\n\nthe tests did not finish within 40 min' })
    const err = await mergePr(PR, exec(), () => {}, () => {}, gate(), rebase, vi.fn(), vi.fn(), {}).catch((e) => e)
    expect(err.payload.code).toBe('GATE_INFRA')
    expect(err.payload.remediation).toMatch(/What failed/)
  })

  it('an unknown machine id still gives a plain sentence, never "undefined"', async () => {
    const rebase = vi.fn().mockResolvedValue({ ok: false, reason: DISK })
    const err = await mergePr(PR, exec(), () => {}, () => {}, gate(), rebase, vi.fn(), vi.fn(), { loadNow: () => ({}) }).catch((e) => e)
    expect(err.payload.message).not.toMatch(/undefined|null/)
    expect(err.payload.message).toMatch(/disk is nearly full/)
  })

  it('hands the first-aid step to the gate', async () => {
    const diskFirstAid = vi.fn()
    const rebase = vi.fn().mockResolvedValue({ ok: true })
    await mergePr(PR, exec(), () => {}, () => {}, gate(), rebase, vi.fn(), vi.fn(), { diskFirstAid }).catch(() => {})
    expect(rebase.mock.calls[0][9]).toBe(diskFirstAid)
  })
})

describe('runDiskFirstAid: the registered step, run through purpose_metrics', () => {
  it('runs only the registered step on this Mac and reads its JSON answer', async () => {
    const exec = vi.fn(async () => ({ stdout: 'noise\n{"step":"disk-clear-rebuildable","ok":true,"changed":true,"detail":"freed 12 MiB"}\n', stderr: '' }))
    const r = await runDiskFirstAid(exec)
    expect(r).toMatchObject({ ok: true, changed: true, detail: 'freed 12 MiB' })
    const [cmd, args, opts] = exec.mock.calls[0]
    expect(cmd).toMatch(/python/)
    expect(args.slice(1)).toEqual(['first-aid', DISK_FIRST_AID_STEP, '--local'])
    expect(args[0]).toMatch(/purpose_metrics\.py$/)
    expect(opts.timeout).toBeGreaterThan(0)
  })

  it('a failing, silent or garbled run is a failed step, never a throw', async () => {
    for (const exec of [
      vi.fn().mockRejectedValue(Object.assign(new Error('Command failed'), { stderr: 'Traceback: boom' })),
      vi.fn(async () => ({ stdout: '', stderr: '' })),
      vi.fn(async () => ({ stdout: 'not json', stderr: '' })),
      vi.fn(async () => ({ stdout: '[1,2]', stderr: '' }))
    ]) {
      const r = await runDiskFirstAid(exec)
      expect(r.ok).toBe(false)
      expect(typeof r.detail).toBe('string')
    }
  })
})
