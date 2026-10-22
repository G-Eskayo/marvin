import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// The gate's other side effects (stage timeline, failure log, version bump...) are tested elsewhere; never real files.
vi.mock('../webhook-server/ticket_stages.js', () => ({ recordStage: vi.fn() }))
vi.mock('../webhook-server/failure_log.js', () => ({ recordFailure: vi.fn() }))
vi.mock('../webhook-server/rebase_status.js', () => ({ writeRebaseStatus: vi.fn(), readRebaseStatus: vi.fn(() => ({})) }))
vi.mock('../webhook-server/ui_evidence.js', () => ({ assertUiEvidence: vi.fn(async () => {}) }))
vi.mock('../webhook-server/decisions_gate.js', () => ({ assertDecisions: vi.fn(async () => {}) }))
vi.mock('../webhook-server/changelog.js', () => ({ applyVersionBump: vi.fn().mockResolvedValue(undefined) }))

import { mkdtempSync, rmSync, readFileSync, writeFileSync, existsSync, mkdirSync, statSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { mergePr, withGateTimeout, execWithGroupTimeout, gateExec, _defaultRunTests, countTestFiles, pytestParallelArgs } from '../webhook-server/merge.js'
import {
  createMergeTracker, createInflightStore, takeInterruptedMerges, recordMergeDuration, estimateMergeMs,
  createCountParser, machineLoad, gateExtension, inflightPath, durationsPath, topProcess
} from '../webhook-server/merge_progress.js'
import { applyMergeEvent, emptyProgress } from '../src/lib/merge_progress.js'

// marvin#568. Every test runs with a temp HOME: the in-flight record and the durations file must never touch the
// real ~/.claude (a test once wiped ~/.claude/logs).
let home, realHome
beforeEach(() => {
  realHome = process.env.HOME
  home = mkdtempSync(path.join(tmpdir(), 'merge-progress-home-'))
  process.env.HOME = home
})
afterEach(() => {
  process.env.HOME = realHome
  rmSync(home, { recursive: true, force: true })
})

const PR = 'https://github.com/G-Eskayo/marvin/pull/559'
const BODY = 'Closes #5'
const noop = () => {}
// A gh that answers the metadata calls and merges.
const gh = (overrides = {}) => vi.fn(async (cmd, args) => {
  const key = args.join(' ')
  for (const [k, v] of Object.entries(overrides)) if (key.includes(k)) return typeof v === 'function' ? v() : v
  if (key.includes('statusCheckRollup')) return { stdout: JSON.stringify({ statusCheckRollup: [] }), stderr: '' }
  if (key.includes('mergeable')) return { stdout: JSON.stringify({ mergeable: 'MERGEABLE' }), stderr: '' }
  return { stdout: '{}', stderr: '' }
})
const gate = (yes = true) => vi.fn(async () => ({ gate: yes, behind: true, shared: yes ? ['x.js'] : [], headRefName: 'pipeline/x', body: BODY }))
const collect = () => {
  const events = []
  return { events, progress: (stage, state, extra) => events.push([stage, state, ...(extra?.detail ? [extra.detail] : [])]) }
}
const stagesOf = (events) => events.filter(([, s]) => s !== 'output').map(([stage, state]) => `${stage}:${state}`)

describe('the gate reports each stage in order', () => {
  it('a retested merge: fetching, rebasing, installing, tests, merging, after-merge checks', async () => {
    const { events, progress } = collect()
    const retest = vi.fn(async (head, exec, repo, runTests, base, resolve, sleep, report) => {
      report('rebasing', 'running'); report('rebasing', 'done')
      report('installing', 'running'); report('installing', 'done')
      report('tests', 'running', { detail: 'Python' }); report('tests', 'done')
      return { ok: true }
    })
    const r = await mergePr(PR, gh(), noop, noop, gate(true), retest, vi.fn(), vi.fn(), { progress })
    expect(r.merged).toBe(true)
    expect(stagesOf(events)).toEqual(['fetching:running', 'fetching:done', 'rebasing:running', 'rebasing:done', 'installing:running', 'installing:done', 'tests:running', 'tests:done', 'merging:running', 'merging:done', 'after:running', 'after:done'])
  })

  it('no retest needed: rebasing, installing and tests are skipped with the reason', async () => {
    const { events, progress } = collect()
    await mergePr(PR, gh(), noop, noop, gate(false), vi.fn(), vi.fn(), vi.fn(), { progress })
    expect(stagesOf(events)).toEqual(['fetching:running', 'fetching:done', 'rebasing:skipped', 'installing:skipped', 'tests:skipped', 'merging:running', 'merging:done', 'after:running', 'after:done'])
    expect(events.find(([s]) => s === 'tests')[2]).toMatch(/no retest needed: main changed none of this PR's files/)
  })

  it('a refusal before the gate leaves fetching running (the tracker marks it failed), nothing after it', async () => {
    const { events, progress } = collect()
    const exec = gh({ baseRefName: { stdout: JSON.stringify({ baseRefName: 'side' }), stderr: '' } })
    await expect(mergePr(PR, exec, noop, noop, gate(true), vi.fn(), vi.fn(), vi.fn(), { progress })).rejects.toMatchObject({ payload: { code: 'WRONG_BASE' } })
    expect(stagesOf(events)).toEqual(['fetching:running'])
  })

  it('a progress reader that throws never breaks the merge', async () => {
    const r = await mergePr(PR, gh(), noop, noop, gate(false), vi.fn(), vi.fn(), vi.fn(), { progress: () => { throw new Error('reader gone') } })
    expect(r.merged).toBe(true)
  })

  it('the real test runner reports installing, then Python, then Dashboard, with the runners\' own counts', async () => {
    const { events, progress } = collect()
    const exec = vi.fn(async (cmd, args, opts) => {
      if (args.includes('pytest')) { opts.onOutput('.....  [ 50%]\n'); opts.onOutput('.....  [100%]\n') }
      if (args.includes('vitest')) { opts.onOutput(' ✓ test/a.test.js (3 tests) 4ms\n ✓ test/b.test.jsx (1 test) 2ms\n') }
      return { stdout: '', stderr: '' }
    })
    const cwd = path.join(home, 'scratch')
    mkdirSync(path.join(cwd, 'dashboard', 'test'), { recursive: true })
    for (const f of ['a.test.js', 'b.test.jsx']) writeFileSync(path.join(cwd, 'dashboard', 'test', f), '')
    await _defaultRunTests(cwd, exec, progress, async () => ['-n', 'auto'])
    expect(exec.mock.calls.map(([c, a]) => a[0] === 'install' ? 'npm install' : a.includes('pytest') ? 'pytest' : 'vitest')).toEqual(['npm install', 'pytest', 'vitest'])
    const counts = events.filter(([s, st]) => s === 'tests' && st === 'running').map((e) => e[2])
    expect(counts).toEqual(['Python', 'Python', 'Python', 'Dashboard', 'Dashboard', 'Dashboard'])
    expect(exec.mock.calls.every(([, , o]) => typeof o.onOutput === 'function')).toBe(true)
  })
})

describe('the time limit under load (#559: three GATE_INFRA cut-offs while the Mac mini ran an engine test)', () => {
  const busy = { id: 'mac-mini-1', load: 9.4, cores: 10, busy: true, top: 'engine test' }
  const idle = { id: 'mac-mini-1', load: 1.2, cores: 10, busy: false }
  // A gate that keeps printing test output for `ms`, then passes.
  const slowGate = (ms, step = 5) => vi.fn(async (h, e, r, rt, b, rc, s, report) => {
    const end = Date.now() + ms
    while (Date.now() < end) { report('tests', 'output'); await new Promise((res) => setTimeout(res, step)) }
    return { ok: true }
  })
  const hangs = () => vi.fn(() => new Promise(() => {}))

  it('busy machine, tests still printing: the limit is extended once, with the reason, and the merge goes through', async () => {
    const { events, progress } = collect()
    const r = await mergePr(PR, gh(), noop, noop, gate(true), slowGate(62), vi.fn(), vi.fn(), { gateTimeoutMs: 50, loadNow: () => busy, progress })
    expect(r.merged).toBe(true)
    const ext = events.find(([s, st, d]) => s === 'tests' && st === 'running' && /extended/.test(d || ''))
    expect(ext[2]).toBe('Mac mini is busy (load 9.4 on 10 cores, engine test running) and the tests are still making progress, so the time limit was extended by 0 min')
  })

  it('busy but extended once already: cut off as GATE_INFRA, the message says it was extended and why', async () => {
    await expect(mergePr(PR, gh(), noop, noop, gate(true), slowGate(400), vi.fn(), vi.fn(), { gateTimeoutMs: 40, loadNow: () => busy }))
      .rejects.toMatchObject({ payload: { code: 'GATE_INFRA', message: expect.stringMatching(/extended once already \(Mac mini is busy/) } })
  })

  it('busy but the tests went quiet: no extension, cut off, and the message says the tests had stopped', async () => {
    const reengage = vi.fn()
    await expect(mergePr(PR, gh(), noop, noop, gate(true), hangs(), reengage, vi.fn(), { gateTimeoutMs: 30, loadNow: () => busy }))
      .rejects.toMatchObject({ payload: { code: 'GATE_INFRA', message: expect.stringMatching(/was busy .*stopped producing output/) } })
    expect(reengage).not.toHaveBeenCalled() // the machine's problem: never sent back for rework
  })

  it('idle machine, tests hung: cut off at the normal limit, "most likely hung"', async () => {
    await expect(mergePr(PR, gh(), noop, noop, gate(true), slowGate(400), vi.fn(), vi.fn(), { gateTimeoutMs: 30, loadNow: () => idle }))
      .rejects.toMatchObject({ payload: { code: 'GATE_INFRA', message: expect.stringMatching(/was not busy \(load 1\.2 on 10 cores\), so the tests most likely hung/) } })
  })

  it('a load reading that throws is no extension, never a crash', async () => {
    const r = await withGateTimeout(new Promise(() => {}), 10, () => { throw new Error('ps missing') })
    expect(r.ok).toBe(false)
    expect(r.reason).toMatch(/did not finish within 1 min and was cut off/)
  })

  it('a gate that finishes in time is never asked about load', async () => {
    const decide = vi.fn()
    expect(await withGateTimeout(Promise.resolve({ ok: true }), 1000, decide)).toEqual({ ok: true })
    expect(decide).not.toHaveBeenCalled()
  })

  it('gateExtension is pure: busy + recent output extends by half; output older than 5 min does not', () => {
    expect(gateExtension({ baseMs: 40 * 60_000, load: busy, lastOutputAt: 1000, now: 2000 }).extendMs).toBe(20 * 60_000)
    expect(gateExtension({ baseMs: 40 * 60_000, load: busy, lastOutputAt: 0, now: 6 * 60_000 }).extendMs).toBe(0)
    expect(gateExtension({ baseMs: 40 * 60_000, load: busy, lastOutputAt: null, now: 1 }).extendMs).toBe(0)
    expect(gateExtension({ baseMs: 40 * 60_000, load: null, lastOutputAt: 1, now: 2 }).note).toMatch(/load unknown/)
  })
})

describe('machine load', () => {
  it('busy at 70% of the cores, naming the long job by its command line', () => {
    const top = () => 'engine test'
    expect(machineLoad({ loadavg: () => [7.04, 0, 0], cpus: () => 10, top, id: 'mac-mini-1' })).toEqual({ id: 'mac-mini-1', load: 7, cores: 10, busy: true, top: 'engine test' })
    const notCalled = vi.fn()
    expect(machineLoad({ loadavg: () => [3.8, 0, 0], cpus: () => 10, top: notCalled })).toMatchObject({ busy: false })
    expect(notCalled).not.toHaveBeenCalled() // ps runs only when the machine is busy
  })

  it('topProcess skips its own ps line and names known jobs; a failing ps is unknown, not a crash', () => {
    const ps = () => ' 99.0 /bin/ps -Ao pcpu=,args= -r\n 95.1 /usr/bin/python3 run_engine_accuracy.py --all\n 3.0 /usr/libexec/sysmond\n'
    expect(topProcess(ps)).toBe('engine test')
    expect(topProcess(() => ' 80.0 /Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild test\n')).toBe('app build')
    expect(topProcess(() => ' 80.0 /usr/local/bin/ffmpeg -i x\n')).toBe('ffmpeg')
    expect(topProcess(() => { throw new Error('no ps') })).toBe(null)
  })
})

describe('live test counts', () => {
  it('pytest: the percent at the end of each line, at most one event per 5 points', () => {
    const seen = []
    const feed = createCountParser('pytest', { onCount: (c) => seen.push(c.done) })
    feed('....... [  1%]\n...... [  2%]\n..... [  3%]\n')
    feed('.... [  6%]\n... [ 50')
    feed('%]\n.. [100%]\n')
    expect(seen).toEqual([1, 6, 50, 100])
  })

  it('vitest: one finished file per ✓/❯/× line, against the counted total; never past it', () => {
    const seen = []
    const feed = createCountParser('vitest', { totalFiles: 4, onCount: (c) => seen.push(`${c.done}/${c.total}`) })
    feed(' ✓ test/a.test.js (3 tests) 4ms\n ❯ test/b.test.jsx (2 tests | 1 failed)\n')
    feed('   × it fails\n') // a failing test inside b, not a file
    feed(' × test/c.test.js (1 test)\n ✓ test/d.test.mjs (1 test)\n ✓ test/e.test.js (1 test)\n')
    expect(seen).toEqual(['1/4', '2/4', '3/4', '4/4', '5/5'])
  })

  it('a 2,000-file run makes about 20 events, not 2,000 (and an unknown total growing as it goes stays bounded too)', () => {
    let grown = 0
    const g = createCountParser('vitest', { totalFiles: 0, onCount: () => grown++ })
    for (let i = 0; i < 300; i++) g(` ✓ test/g${i}.test.js (1 test)\n`)
    expect(grown).toBe(12) // every 25th file when no total is known

    let n = 0
    const feed = createCountParser('vitest', { totalFiles: 2000, onCount: () => n++ })
    for (let i = 0; i < 2000; i++) feed(` ✓ test/f${i}.test.js (1 test)\n`)
    expect(n).toBeLessThanOrEqual(21)
  })

  it('junk output is ignored', () => {
    const feed = createCountParser('pytest', { onCount: () => { throw new Error('should not fire') } })
    feed(Buffer.from([0xff, 0xfe]))
    feed('[ 999%] nope\n')
    feed('')
  })

  it('countTestFiles counts test files, not node_modules; a missing folder is 0', () => {
    const d = path.join(home, 'dash', 'test')
    mkdirSync(path.join(d, 'sub'), { recursive: true })
    mkdirSync(path.join(d, 'node_modules'), { recursive: true })
    for (const f of ['a.test.js', 'sub/b.test.jsx', 'helper.js', 'node_modules/c.test.js']) writeFileSync(path.join(d, f), '')
    expect(countTestFiles(d)).toBe(2)
    expect(countTestFiles(path.join(home, 'none'))).toBe(0)
  })

  it('execWithGroupTimeout hands each output chunk to onOutput and still returns all of it', async () => {
    const chunks = []
    const r = await execWithGroupTimeout('/bin/sh', ['-c', 'echo one; echo two >&2'], { onOutput: (c) => chunks.push(c) }, 5000)
    expect(r.stdout).toBe('one\n')
    expect(chunks.join('')).toMatch(/one/)
    expect(chunks.join('')).toMatch(/two/)
  })
})

describe('the tracker: events, log lines, the in-flight record', () => {
  const make = (extra = {}) => {
    const lines = [], sent = []
    let t = Date.parse('2026-10-21T19:00:00Z')
    const tracker = createMergeTracker({ url: PR, repo: 'G-Eskayo/marvin', machineId: 'mac-mini-1', emit: (e) => sent.push(e), log: (l) => lines.push(l), inflight: createInflightStore(), now: () => (t += 1000), id: 'a1', ...extra })
    return { tracker, lines, sent }
  }

  it('numbers each event, logs each stage change once, and records the merge in flight until it ends', () => {
    const { tracker, lines, sent } = make()
    tracker.start(1)
    tracker.progress('fetching', 'running')
    expect(JSON.parse(readFileSync(inflightPath(), 'utf-8'))[PR]).toMatchObject({ id: 'a1', seq: 2, stage: 'fetching' })
    tracker.progress('tests', 'running', { count: { done: 1, total: 10, unit: 'files' } })
    tracker.progress('tests', 'running', { count: { done: 5, total: 10, unit: 'files' } })
    tracker.progress('tests', 'output')
    tracker.finish({ merged: true })
    expect(sent.map((e) => e.seq)).toEqual([1, 2, 3, 4, 5])
    expect(sent.every((e) => e.id === 'a1')).toBe(true)
    expect(lines[0]).toBe('[merge] G-Eskayo/marvin#559 started on Mac mini (1 merge ahead in the queue)')
    expect(lines.filter((l) => / tests running/.test(l))).toHaveLength(1) // counts are not logged
    expect(lines.at(-1)).toMatch(/^\[merge\] G-Eskayo\/marvin#559 finished: merged after 0:0\d$/)
    expect(JSON.parse(readFileSync(inflightPath(), 'utf-8'))).toEqual({})
  })

  it('a refusal marks the running stage failed and logs why', () => {
    const { tracker, lines, sent } = make()
    tracker.start()
    tracker.progress('fetching', 'running')
    tracker.fail({ code: 'WRONG_BASE', message: 'this PR targets "side", not main' })
    expect(sent.at(-1)).toMatchObject({ stage: 'fetching', state: 'failed', detail: 'WRONG_BASE: this PR targets "side", not main' })
    expect(lines.at(-1)).toMatch(/finished: refused after .* \(WRONG_BASE/)
  })

  it('a send-back marks the running stage failed', () => {
    const { tracker, sent } = make()
    tracker.start(); tracker.progress('tests', 'running')
    tracker.finish({ merged: false, reengaged: true, code: 'GATE_TESTS_FAILED' })
    expect(sent.at(-1)).toMatchObject({ stage: 'tests', state: 'failed', detail: 'GATE_TESTS_FAILED: sent back for rework' })
  })

  it('measures the machine as the merge starts and as the tests start, once each', () => {
    const measure = vi.fn(() => ({ load: 9.4, cores: 10, busy: true, top: 'engine test' }))
    const { tracker, sent, lines } = make({ measure })
    tracker.start(); tracker.progress('fetching', 'running'); tracker.progress('tests', 'running', { detail: 'Python' }); tracker.progress('tests', 'running', { detail: 'Dashboard' })
    expect(measure).toHaveBeenCalledTimes(2)
    expect(sent[1].machine).toEqual({ id: 'mac-mini-1', load: 9.4, cores: 10, busy: true, top: 'engine test' })
    expect(lines.some((l) => l.includes('[Mac mini busy: load 9.4 on 10 cores, engine test]'))).toBe(true)
  })

  it('an emit that throws (the dashboard went away) does not stop the merge record', () => {
    const { tracker } = make({ emit: () => { throw new Error('socket closed') } })
    expect(() => { tracker.start(); tracker.finish({ merged: true }) }).not.toThrow()
  })

  it('duplicate calls produce no duplicate event', () => {
    const { tracker, sent } = make()
    tracker.start(); tracker.progress('fetching', 'done'); tracker.progress('fetching', 'done')
    expect(sent).toHaveLength(2)
  })
})

describe('a webhook restart mid-merge', () => {
  it('the next start finds the merge in flight, logs it, clears the record, and gives one "interrupted" event each', () => {
    const store = createInflightStore()
    store.set(PR, { id: 'a1', seq: 6, stage: 'tests', startedAt: 1, machine: 'mac-mini-1' })
    const lines = []
    const lost = takeInterruptedMerges(inflightPath(), { log: (l) => lines.push(l), now: () => 99 })
    expect(lost).toEqual([{ url: PR, event: { id: 'a1', seq: 7, stage: 'tests', state: 'failed', interrupted: true, at: 99, detail: 'interrupted: the webhook restarted' } }])
    expect(lines[0]).toMatch(/G-Eskayo\/marvin#559 interrupted: the webhook restarted while it was at "tests"/)
    expect(JSON.parse(readFileSync(inflightPath(), 'utf-8'))).toEqual({})
    // ...and the dashboard's reducer turns that one event into a failed Tests row.
    let p = applyMergeEvent(emptyProgress(), { id: 'a1', seq: 6, stage: 'tests', state: 'running', at: 1 })
    p = applyMergeEvent(p, lost[0].event)
    expect(p.stages.tests.state).toBe('failed')
  })

  it('nothing in flight, a missing file, or a corrupt one: no events, no crash', () => {
    expect(takeInterruptedMerges(inflightPath(), { log: noop })).toEqual([])
    mkdirSync(path.dirname(inflightPath()), { recursive: true })
    writeFileSync(inflightPath(), '{not json')
    expect(takeInterruptedMerges(inflightPath(), { log: noop })).toEqual([])
    writeFileSync(inflightPath(), JSON.stringify({ 'javascript:alert(1)': { stage: 'tests' }, [PR]: { stage: '../../etc', seq: 'x' } }))
    const lost = takeInterruptedMerges(inflightPath(), { log: noop })
    expect(lost.map((l) => l.url)).toEqual([PR])
    expect(lost[0].event).toMatchObject({ stage: 'queued', seq: 1 })
  })
})

describe('real gate durations (the old file only ever had durationMs: 0)', () => {
  it('a finished merge records its real duration and stage times; the estimate is the median of the same kind', () => {
    let t = 0
    const make = (gated, ms) => {
      const tr = createMergeTracker({ url: PR, repo: 'G-Eskayo/marvin', emit: noop, log: noop, record: recordMergeDuration, now: () => t, id: `x${t}` })
      tr.start(); tr.progress('fetching', 'running'); tr.progress('fetching', 'done', { gated })
      t += ms
      tr.finish({ merged: true })
    }
    make(true, 170_000); make(true, 190_000); make(true, 600_000); make(false, 20_000)
    const lines = readFileSync(durationsPath(), 'utf-8').trim().split('\n').map((l) => JSON.parse(l))
    expect(lines.map((l) => l.durationMs)).toEqual([170_000, 190_000, 600_000, 20_000])
    expect(lines[0]).toMatchObject({ repo: 'G-Eskayo/marvin', gated: true, outcome: 'merged' })
    expect(estimateMergeMs('G-Eskayo/marvin', true)).toBe(190_000)
    expect(estimateMergeMs('G-Eskayo/marvin', false)).toBe(20_000)
    expect(estimateMergeMs('G-Eskayo/other', true)).toBe(null)
  })

  it('the old 0 ms lines and junk are ignored; a 0 ms duration is never written', () => {
    mkdirSync(path.dirname(durationsPath()), { recursive: true })
    writeFileSync(durationsPath(), '{"t":"2026-10-17T12:16:14.415Z","key":"pytest","durationMs":0,"passed":true}\nnot json\n')
    recordMergeDuration({ repo: 'G-Eskayo/marvin', gated: true, outcome: 'merged', durationMs: 0 })
    expect(readFileSync(durationsPath(), 'utf-8').split('\n').filter(Boolean)).toHaveLength(2)
    expect(estimateMergeMs('G-Eskayo/marvin', true)).toBe(null)
  })

  it('the estimate is fed to the dashboard once the path (retested or not) is known', () => {
    const sent = []
    const tr = createMergeTracker({ url: PR, repo: 'G-Eskayo/marvin', emit: (e) => sent.push(e), log: noop, estimate: (repo, gated) => (gated ? 185_000 : null), id: 'e1' })
    tr.start(); tr.progress('fetching', 'running'); tr.progress('fetching', 'done', { gated: true })
    expect(sent.at(-1).estimateMs).toBe(185_000)
  })

  it('stays bounded: trimmed to the last 500 lines past 256 KB, and only the tail is read', () => {
    const line = JSON.stringify({ repo: 'G-Eskayo/marvin', gated: true, outcome: 'merged', durationMs: 1000, pad: 'x'.repeat(600) })
    mkdirSync(path.dirname(durationsPath()), { recursive: true })
    writeFileSync(durationsPath(), (line + '\n').repeat(450))
    recordMergeDuration({ repo: 'G-Eskayo/marvin', gated: true, outcome: 'merged', durationMs: 2000 })
    expect(statSync(durationsPath()).size).toBeLessThan(400 * 1024)
    expect(readFileSync(durationsPath(), 'utf-8').trim().split('\n').length).toBeLessThanOrEqual(500)
    expect(estimateMergeMs('G-Eskayo/marvin', true)).toBe(1000)
  })
})

describe('nothing is written outside the temp HOME', () => {
  it('paths follow HOME at call time', () => {
    expect(inflightPath().startsWith(home)).toBe(true)
    expect(durationsPath().startsWith(home)).toBe(true)
    expect(existsSync(path.join(realHome, '.claude', 'logs', 'merge-inflight.json.' + process.pid + '.tmp'))).toBe(false)
  })
})

// Pipeline review 2026-10-21, F3: the 20-minute per-command kill fired before the 40-minute gate limit, so #568's
// load-aware extension could never apply. Inside the gate there is now one clock: the gate's.
describe('one clock inside the gate', () => {
  const alive = (pid) => { try { process.kill(pid, 0); return true } catch { return false } }
  const waitFor = async (cond, ms = 3000) => { const end = Date.now() + ms; while (!cond() && Date.now() < end) await new Promise((r) => setTimeout(r, 20)); return cond() }

  it('no per-command limit (Infinity) means none: it does not fire at once (setTimeout overflow) or at all', async () => {
    const r = await execWithGroupTimeout('/bin/sh', ['-c', 'sleep 0.3; echo done'], {}, Infinity)
    expect(r.stdout).toBe('done\n')
    for (const t of [0, -1, NaN, null]) expect((await execWithGroupTimeout('/bin/sh', ['-c', 'echo ok'], {}, t)).stdout).toBe('ok\n')
  })

  it('aborting the signal kills the whole process group, grandchildren included, and says it was cut off', async () => {
    const ac = new AbortController()
    let out = ''
    const run = execWithGroupTimeout('/bin/sh', ['-c', 'sleep 30 & echo $!; wait'], { signal: ac.signal, onOutput: (c) => { out += c } }, Infinity)
    expect(await waitFor(() => /\d+/.test(out))).toBe(true)
    const grandchild = Number(out.trim())
    expect(alive(grandchild)).toBe(true)
    ac.abort()
    await expect(run).rejects.toThrow(/Cut off: the merge gate's time limit ran out/)
    expect(await waitFor(() => !alive(grandchild))).toBe(true)
  })

  it('an already aborted signal never starts the command', async () => {
    const ac = new AbortController()
    ac.abort()
    const marker = path.join(home, 'started')
    await expect(execWithGroupTimeout('/usr/bin/touch', [marker], { signal: ac.signal })).rejects.toThrow(/before it started/)
    expect(existsSync(marker)).toBe(false)
  })

  it('a signal that is never aborted leaves no listener behind once the command ends', async () => {
    const ac = new AbortController()
    for (let i = 0; i < 20; i++) await execWithGroupTimeout('/bin/sh', ['-c', 'true'], { signal: ac.signal }, Infinity)
    // Node warns past 10 listeners on one signal; removing each keeps it at 0 (bounded across a whole gate run).
    const { getEventListeners } = await import('events')
    expect(getEventListeners(ac.signal, 'abort').length).toBe(0)
  })

  it('gateExec: while the gate runs, every command gets its signal and no limit of its own; after a cut, cleanup runs normally', async () => {
    const inner = vi.fn(async () => ({ stdout: '', stderr: '' }))
    const ac = new AbortController()
    const run = gateExec(inner, ac.signal)
    await run('git', ['fetch'], { cwd: '/x' })
    expect(inner).toHaveBeenLastCalledWith('git', ['fetch'], { cwd: '/x', signal: ac.signal }, Infinity)
    await run('pytest', [], {}, 5000) // an explicit limit is kept
    expect(inner).toHaveBeenLastCalledWith('pytest', [], { signal: ac.signal }, 5000)
    ac.abort()
    await run('git', ['worktree', 'remove'], { cwd: '/x' })
    expect(inner).toHaveBeenLastCalledWith('git', ['worktree', 'remove'], { cwd: '/x' }, undefined)
  })

  it('withGateTimeout calls onCut exactly once when it cuts, and never when the gate finishes (extended or not)', async () => {
    const onCut = vi.fn()
    await withGateTimeout(new Promise(() => {}), 10, () => ({ extendMs: 0, note: 'idle' }), noop, onCut)
    expect(onCut).toHaveBeenCalledTimes(1)
    const onCut2 = vi.fn()
    await withGateTimeout(new Promise(() => {}), 10, () => ({ extendMs: 10, reason: 'busy' }), noop, onCut2)
    expect(onCut2).toHaveBeenCalledTimes(1)
    const onCut3 = vi.fn()
    await withGateTimeout(new Promise((r) => setTimeout(() => r({ ok: true }), 15)), 10, () => ({ extendMs: 100, reason: 'busy' }), noop, onCut3)
    expect(onCut3).not.toHaveBeenCalled()
    const onCut4 = vi.fn()
    expect(await withGateTimeout(Promise.resolve({ ok: true }), 10, noop, noop, onCut4)).toEqual({ ok: true })
    expect(onCut4).not.toHaveBeenCalled()
    expect((await withGateTimeout(new Promise(() => {}), 10, noop, noop, () => { throw new Error('boom') })).ok).toBe(false)
  })

  it('a cut-off gate kills its running command: the real tests do not keep running behind the next merge', async () => {
    let pid = null
    const retest = vi.fn(async (head, exec) => {
      let out = ''
      await exec('/bin/sh', ['-c', 'echo $$; sleep 30'], { onOutput: (c) => { out += c; pid = pid ?? Number(out.trim()) } })
      return { ok: true }
    })
    const realExec = (cmd, args, opts, t) => (cmd === '/bin/sh' ? execWithGroupTimeout(cmd, args, opts, t) : gh()(cmd, args, opts))
    await expect(mergePr(PR, realExec, noop, noop, gate(true), retest, vi.fn(), vi.fn(), { gateTimeoutMs: 300, loadNow: () => ({ busy: false, load: 0.5, cores: 10 }) }))
      .rejects.toMatchObject({ payload: { code: 'GATE_INFRA' } })
    expect(pid).toBeGreaterThan(0)
    expect(await waitFor(() => !alive(pid))).toBe(true)
  })

  it('a test run longer than the old 20-minute per-command kill is bounded only by the gate (the kill is no longer passed)', async () => {
    const seen = []
    const retest = vi.fn(async (head, exec) => { await exec('pytest', ['-q'], {}); return { ok: true } })
    const exec = vi.fn(async (cmd, args, opts, t) => { if (cmd === 'pytest') seen.push(t); return gh()(cmd, args, opts) })
    const r = await mergePr(PR, exec, noop, noop, gate(true), retest, vi.fn(), vi.fn(), {})
    expect(r.merged).toBe(true)
    expect(seen).toEqual([Infinity])
  })
})

// The Python suite in parallel (pytest-xdist): 327 s serial vs 47 s on the M4, 2026-10-21.
describe('the gate runs the Python suite in parallel when it can', () => {
  it('pytestParallelArgs: the plugin imports, so -n auto', async () => {
    const run = vi.fn(async () => ({ stdout: '', stderr: '' }))
    expect(await pytestParallelArgs('/venv/python', run, vi.fn())).toEqual(['-n', 'auto'])
    expect(run).toHaveBeenCalledWith('/venv/python', ['-c', 'import xdist'])
  })

  it('no plugin: serial, with a log line that names the fix; a throwing logger changes nothing', async () => {
    const log = vi.fn()
    const missing = async () => { throw Object.assign(new Error('exit 1'), { stderr: 'No module named xdist' }) }
    expect(await pytestParallelArgs('/venv/python', missing, log)).toEqual([])
    expect(log.mock.calls[0][0]).toMatch(/pytest-xdist is not installed in \/venv\/python: running the Python suite serially.*pip install pytest-xdist/)
    expect(await pytestParallelArgs('/venv/python', missing, () => { throw new Error('closed') })).toEqual([])
  })

  it('a real python that cannot import it, or no python at all, is serial, never a crash', async () => {
    const fake = path.join(home, 'python')
    writeFileSync(fake, '#!/bin/sh\nexit 1\n', { mode: 0o755 })
    expect(await pytestParallelArgs(fake, undefined, vi.fn())).toEqual([])
    expect(await pytestParallelArgs(path.join(home, 'nope'), undefined, vi.fn())).toEqual([])
  })

  it('_defaultRunTests passes the parallel args to pytest only, and says when it runs serially', async () => {
    for (const [args, detail] of [[['-n', 'auto'], 'Python'], [[], 'Python (serial: pytest-xdist missing)']]) {
      const calls = [], events = []
      const exec = vi.fn(async (cmd, a) => { calls.push(a); return { stdout: '', stderr: '' } })
      await _defaultRunTests(path.join(home, 'scratch'), exec, (s, st, e) => events.push([s, st, e?.detail]), async () => args)
      const py = calls.find((a) => a.includes('pytest'))
      expect(py).toEqual(['-m', 'pytest', '-q', ...args])
      expect(calls.find((a) => a.includes('vitest'))).toEqual(['vitest', 'run'])
      expect(events.some(([s, st, d]) => s === 'tests' && st === 'running' && d === detail)).toBe(true)
    }
  })
})
