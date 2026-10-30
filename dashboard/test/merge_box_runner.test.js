// mac-mini-2012 as the merge gate's extra runner (marvin #933): handed the same commit, recorded beside the Mac's
// verdict, and never able to change the gate's result or hold it up.
import { describe, it, expect, vi } from 'vitest'
import { EventEmitter } from 'events'
import { _defaultRunTests, makeBoxRunner, noBoxRunner } from '../webhook-server/merge.js'

const cache = { seed: async () => {}, store: async () => {} }
const serial = async () => []
// The gate runs each required check through .github/run-check.sh (#826); the Python one is `python`.
const slot = async () => ({ release: async () => {} })
const run = (exec, box) => _defaultRunTests('/scratch', exec, undefined, serial, cache, null, slot, box)

function gateExec({ pytestFails = false } = {}) {
  const calls = []
  const exec = vi.fn(async (cmd, args) => {
    calls.push([cmd, args[0], args[1]])
    if (pytestFails && args[1] === 'python') {
      const err = new Error('Command failed')
      err.stdout = 'FAILED lib/tests/test_x.py::test_y - boom\n1 failed'
      throw err
    }
    return { stdout: '', stderr: '' }
  })
  return { exec, calls }
}

function fakeBox({ submit } = {}) {
  const box = { sent: [], verdicts: [] }
  box.submit = vi.fn(submit || (async (cwd) => { box.sent.push(cwd); return { id: 'r1', sha: 'a'.repeat(40) } }))
  box.verdict = vi.fn((sent, outcome, output) => box.verdicts.push([sent?.sha ?? null, outcome, output ?? '']))
  return box
}

describe('the gate with the box beside it', () => {
  it("hands the box the gate's own tree and records the Mac's pass", async () => {
    const { exec } = gateExec()
    const box = fakeBox()
    await run(exec, box)
    expect(box.sent).toEqual(['/scratch'])
    expect(box.verdicts).toEqual([['a'.repeat(40), 'passed', '']])
  })

  it("records the Mac's failure with its output, and the failure is still the gate's (thrown, unchanged)", async () => {
    const { exec } = gateExec({ pytestFails: true })
    const box = fakeBox()
    await expect(run(exec, box)).rejects.toThrow('Command failed')
    const [[sha, outcome, output]] = box.verdicts
    expect([sha, outcome]).toEqual(['a'.repeat(40), 'failed'])
    expect(output).toContain('FAILED lib/tests/test_x.py::test_y')
  })

  it('a box hand-off that throws or rejects changes nothing about the gate', async () => {
    for (const submit of [async () => { throw new Error('ssh exploded') }, () => { throw new Error('sync throw') }]) {
      const { exec, calls } = gateExec()
      const box = fakeBox({ submit })
      await expect(run(exec, box)).resolves.toBeUndefined()
      expect(calls.some((c) => c[2] === 'python')).toBe(true)
      expect(box.verdicts).toEqual([[null, 'passed', '']])
    }
  })

  it("doesn't wait for a slow hand-off before starting the Mac's tests", async () => {
    let release
    const order = []
    const box = fakeBox({ submit: () => new Promise((r) => { release = () => { order.push('hand-off done'); r({ id: 'r', sha: 'b'.repeat(40) }) } }) })
    const exec = vi.fn(async (cmd, args) => {
      if (args[1] === 'python') { order.push('pytest started'); setTimeout(() => release(), 20) }
      return { stdout: '', stderr: '' }
    })
    await run(exec, box)
    expect(order).toEqual(['pytest started', 'hand-off done'])
    expect(box.verdicts[0][0]).toBe('b'.repeat(40))
  })

  it('the box runs the Python suite only: vitest results are never recorded against it', async () => {
    const { exec } = gateExec()
    const box = fakeBox()
    await run(exec, box)
    expect(box.verdicts).toHaveLength(1)
  })

  it('by default (every other caller and test) there is no box runner at all', async () => {
    const { exec, calls } = gateExec()
    await run(exec)
    expect(calls.some((c) => String(c[1]).includes('box_runner'))).toBe(false)
    await expect(noBoxRunner.submit('/x')).resolves.toBeNull()
  })
})

describe('makeBoxRunner', () => {
  it('submit returns what box_runner.py printed and says so in the gate log', async () => {
    const run = vi.fn(async () => ({ stdout: '{"id": "r9", "sha": "' + 'c'.repeat(40) + '"}\n' }))
    const progress = vi.fn()
    const sent = await makeBoxRunner({ run, script: '/x/box_runner.py', python: '/py' }).submit('/scratch', progress)
    expect(sent.sha).toBe('c'.repeat(40))
    expect(run).toHaveBeenCalledWith('/py', ['/x/box_runner.py', 'submit', '--tree', '/scratch'], { timeout: 15000 })
    expect(progress.mock.calls[0][2].detail).toMatch(/mac-mini-2012 runs it too \(extra runner, not the verdict\): cccccccc/)
  })

  it.each([
    ['a failing call', async () => { throw new Error('no python') }],
    ['switched off (prints null)', async () => ({ stdout: 'null\n' })],
    ['garbage output', async () => ({ stdout: 'Traceback (most recent call last):' })],
    ['an empty answer', async () => ({ stdout: '' })]
  ])('submit with %s is null, never a throw', async (_, run) => {
    await expect(makeBoxRunner({ run }).submit('/scratch')).resolves.toBeNull()
  })

  it("verdict hands the Mac's output to box_runner.py on stdin, detached", () => {
    const child = Object.assign(new EventEmitter(), { stdin: Object.assign(new EventEmitter(), { end: vi.fn() }), unref: vi.fn() })
    const spawnFn = vi.fn(() => child)
    makeBoxRunner({ spawnFn, script: '/x/box_runner.py', python: '/py' }).verdict({ sha: 'd'.repeat(40) }, 'failed', 'FAILED a.py::t')
    expect(spawnFn).toHaveBeenCalledWith('/py', ['/x/box_runner.py', 'verdict', '--sha', 'd'.repeat(40), '--outcome', 'failed'],
      { stdio: ['pipe', 'ignore', 'ignore'], detached: true })
    expect(child.stdin.end).toHaveBeenCalledWith('FAILED a.py::t')
    expect(child.unref).toHaveBeenCalled()
    child.emit('error', new Error('ENOENT'))   // a late spawn error is swallowed, not an unhandled event
  })

  it('verdict with nothing sent, or a spawn that throws, does nothing and never throws', () => {
    const spawnFn = vi.fn(() => { throw new Error('EAGAIN') })
    const runner = makeBoxRunner({ spawnFn })
    expect(() => runner.verdict(null, 'passed')).not.toThrow()
    expect(spawnFn).not.toHaveBeenCalled()
    expect(() => runner.verdict({ sha: 'e'.repeat(40) }, 'passed')).not.toThrow()
  })

  it('a huge test log is cut to its tail before it is handed over', () => {
    const child = Object.assign(new EventEmitter(), { stdin: Object.assign(new EventEmitter(), { end: vi.fn() }), unref: vi.fn() })
    makeBoxRunner({ spawnFn: () => child }).verdict({ sha: 'f'.repeat(40) }, 'failed', 'x'.repeat(100000) + 'END')
    const sent = child.stdin.end.mock.calls[0][0]
    expect(sent.length).toBe(20000)
    expect(sent.endsWith('END')).toBe(true)
  })
})
