// marvin#866: the merge gate's temporary clones ($TMPDIR/mr-merge-gate-*, ~660 MB each) must not outlive their merge.
// Every test points the gate at a temp root of its own (gateClones.root), never the real $TMPDIR, and uses throwaway
// git repos. "Interrupted" is covered twice: in process (the gate's limit aborts the run, or something throws), and
// across a restart (the process died before its finally ran; the startup sweep clears it).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { execFile, execFileSync } from 'child_process'
import { promisify } from 'util'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, readdirSync, existsSync, utimesSync, symlinkSync, readFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { fileURLToPath } from 'url'
import {
  rebaseAndRetest,
  gateClones,
  sweepGateClones,
  GATE_CLONE_MAX_AGE_MS,
  gateExec,
  execWithGroupTimeout
} from '../webhook-server/merge.js'

const realExec = promisify(execFile)
const sh = (cmd, args, cwd) => execFileSync(cmd, args, { cwd, encoding: 'utf-8' })
const HOUR = 3600_000

let root, scratch, savedRoot
beforeEach(() => {
  root = mkdtempSync(path.join(tmpdir(), 'gate-clones-test-'))
  scratch = path.join(root, 'T')
  mkdirSync(scratch)
  savedRoot = gateClones.root
  gateClones.root = () => scratch
})
afterEach(() => {
  gateClones.root = savedRoot
  gateClones.live.clear()
  rmSync(root, { recursive: true, force: true })
})

const clonesLeft = () => readdirSync(scratch).filter((n) => n.startsWith('mr-merge-gate-'))

// A repo whose feature branch is one commit behind a moved-on main: the gate rebases it, tests it, pushes it.
function fixture() {
  const originDir = path.join(root, 'origin.git')
  const repoDir = path.join(root, 'repo')
  sh('git', ['init', '--quiet', '--bare', originDir])
  sh('git', ['clone', '--quiet', originDir, repoDir])
  sh('git', ['config', 'user.email', 't@t'], repoDir)
  sh('git', ['config', 'user.name', 'T'], repoDir)
  writeFileSync(path.join(repoDir, 'README.md'), 'hello\n')
  sh('git', ['add', '.'], repoDir)
  sh('git', ['commit', '-q', '-m', 'init'], repoDir)
  sh('git', ['branch', '-M', 'main'], repoDir)
  sh('git', ['push', '-q', '-u', 'origin', 'main'], repoDir)
  sh('git', ['checkout', '-q', '-b', 'feature'], repoDir)
  writeFileSync(path.join(repoDir, 'feature.txt'), 'x\n')
  sh('git', ['add', '.'], repoDir)
  sh('git', ['commit', '-q', '-m', 'feature'], repoDir)
  sh('git', ['push', '-q', '-u', 'origin', 'feature'], repoDir)
  sh('git', ['checkout', '-q', 'main'], repoDir)
  writeFileSync(path.join(repoDir, 'main.txt'), 'y\n')
  sh('git', ['add', '.'], repoDir)
  sh('git', ['commit', '-q', '-m', 'main moved'], repoDir)
  sh('git', ['push', '-q', 'origin', 'main'], repoDir)
  return repoDir
}

const roomy = async () => 100 * 1024 ** 3

describe('the gate removes its clone whatever happens to the merge', () => {
  it('after a merged run', async () => {
    const repo = fixture()
    let seen = null
    const r = await rebaseAndRetest('feature', realExec, repo, async (dir) => { seen = dir; expect(clonesLeft()).toHaveLength(1) },
      'main', null, null, undefined, roomy)
    expect(r).toEqual({ ok: true })
    expect(seen.startsWith(scratch)).toBe(true)
    expect(clonesLeft()).toEqual([])
    expect(gateClones.live.size).toBe(0)
    expect(sh('git', ['worktree', 'list'], repo)).not.toContain('mr-merge-gate-')
  })

  it('after a failed run (tests fail)', async () => {
    const repo = fixture()
    const r = await rebaseAndRetest('feature', realExec, repo, async () => { throw new Error('2 failed') }, 'main', null, null, undefined, roomy)
    expect(r.ok).toBe(false)
    expect(clonesLeft()).toEqual([])
  })

  it('after a failed run that throws (GitHub never takes the push)', async () => {
    const repo = fixture()
    const exec = async (cmd, args, opts) => {
      if (cmd === 'git' && args[0] === 'push') throw Object.assign(new Error('push'), { stderr: 'fatal: repository not found' })
      return realExec(cmd, args, opts)
    }
    await expect(rebaseAndRetest('feature', exec, repo, async () => {}, 'main', null, async () => {}, undefined, roomy)).rejects.toThrow()
    expect(clonesLeft()).toEqual([])
    expect(gateClones.live.size).toBe(0)
  })

  it('after an interrupted run (the gate\'s limit aborts the tests mid-way)', async () => {
    const repo = fixture()
    const ac = new AbortController()
    const exec = gateExec((cmd, args, opts, t) => execWithGroupTimeout(cmd, args, opts, t), ac.signal)
    const runTests = async (dir, ex) => {
      setTimeout(() => ac.abort(), 200)
      await ex('sleep', ['30'], { cwd: dir })
    }
    const started = Date.now()
    const r = await rebaseAndRetest('feature', exec, repo, runTests, 'main', null, null, undefined, roomy)
    expect(Date.now() - started).toBeLessThan(20_000)
    expect(r.ok).toBe(false)
    expect(clonesLeft()).toEqual([])
  })

  it('when something throws the moment the clone exists (before any git command)', async () => {
    const repo = fixture()
    const progress = vi.fn((stage) => { if (stage === 'rebasing') throw new Error('progress reader broke') })
    await expect(rebaseAndRetest('feature', realExec, repo, async () => {}, 'main', null, null, progress, roomy)).rejects.toThrow('progress reader broke')
    expect(clonesLeft()).toEqual([])
    expect(gateClones.live.size).toBe(0)
  })

  it('even when git refuses to remove the worktree', async () => {
    const repo = fixture()
    const exec = async (cmd, args, opts) => {
      if (cmd === 'git' && args[0] === 'worktree' && args[1] === 'remove') throw new Error('git said no')
      return realExec(cmd, args, opts)
    }
    await rebaseAndRetest('feature', exec, repo, async () => {}, 'main', null, null, undefined, roomy)
    expect(clonesLeft()).toEqual([])
  })
})

describe('startup sweep of clones a dead process left behind', () => {
  const make = (name, hoursOld) => {
    const d = path.join(scratch, name)
    mkdirSync(path.join(d, 'node_modules'), { recursive: true })
    writeFileSync(path.join(d, 'node_modules', 'big'), 'x'.repeat(1024))
    const t = (Date.now() - hoursOld * HOUR) / 1000
    utimesSync(d, t, t)
    return d
  }
  const dead = () => false

  it('removes clones older than 2 h and keeps younger ones', async () => {
    const old = make('mr-merge-gate-111-aaaaaa', 3)
    const legacy = make('mr-merge-gate-Xy12Ab', 5)          // a name from before pids were in it
    const young = make('mr-merge-gate-222-bbbbbb', 1)
    const r = await sweepGateClones({ isAlive: dead, repoPath: null })
    expect(existsSync(old)).toBe(false)
    expect(existsSync(legacy)).toBe(false)
    expect(existsSync(young)).toBe(true)
    expect(r.removed.sort()).toEqual(['mr-merge-gate-111-aaaaaa', 'mr-merge-gate-Xy12Ab'])
    expect(GATE_CLONE_MAX_AGE_MS).toBe(2 * HOUR)
  })

  it('also removes old baseline copies (mr-baseline-*), which leak the same way', async () => {
    const b = make('mr-baseline-333-cccccc', 3)
    await sweepGateClones({ isAlive: dead, repoPath: null })
    expect(existsSync(b)).toBe(false)
  })

  it('keeps the clone of a merge running in this process, however old it looks', async () => {
    const d = make(`mr-merge-gate-${process.pid}-dddddd`, 30)
    gateClones.live.add(d)
    const r = await sweepGateClones({ isAlive: dead, repoPath: null })
    expect(existsSync(d)).toBe(true)
    expect(r.kept.map((k) => k.name)).toContain(path.basename(d))
  })

  it('keeps a merge\'s clone while the sweep runs in the middle of it, then the merge still cleans it up', async () => {
    const repo = fixture()
    let during = null
    const r = await rebaseAndRetest('feature', realExec, repo, async (dir) => {
      during = await sweepGateClones({ maxAgeMs: 0, isAlive: dead, repoPath: repo })   // everything "old"
      expect(existsSync(dir)).toBe(true)
    }, 'main', null, null, undefined, roomy)
    expect(r).toEqual({ ok: true })
    expect(during.removed).toEqual([])
    expect(clonesLeft()).toEqual([])
  })

  it('keeps an old clone that names another live gate process, removes one whose process is gone', async () => {
    const alive = make('mr-merge-gate-424242-eeeeee', 5)
    const gone = make('mr-merge-gate-535353-ffffff', 5)
    await sweepGateClones({ isAlive: (pid) => pid === 424242, repoPath: null })
    expect(existsSync(alive)).toBe(true)
    expect(existsSync(gone)).toBe(false)
  })

  it('an old clone named for this process but no longer in flight is a leftover and goes', async () => {
    const d = make(`mr-merge-gate-${process.pid}-gggggg`, 5)
    await sweepGateClones({ isAlive: () => true, repoPath: null })
    expect(existsSync(d)).toBe(false)
  })

  it('touches nothing else in the temp folder and never follows a link', async () => {
    const other = make('pytest-of-someone', 50)
    const outside = path.join(root, 'precious')
    mkdirSync(outside)
    writeFileSync(path.join(outside, 'keep.txt'), 'mine')
    symlinkSync(outside, path.join(scratch, 'mr-merge-gate-999-link00'))
    const d = make('mr-merge-gate-777-hhhhhh', 5)
    symlinkSync(outside, path.join(d, 'out'))
    const t = (Date.now() - 5 * HOUR) / 1000
    utimesSync(d, t, t)   // adding the link touched it
    await sweepGateClones({ isAlive: dead, repoPath: null })
    expect(existsSync(other)).toBe(true)
    expect(readFileSync(path.join(outside, 'keep.txt'), 'utf-8')).toBe('mine')
    expect(existsSync(d)).toBe(false)
  })

  it('drops git\'s record of a swept clone, so the repo does not list a missing worktree', async () => {
    const repo = fixture()
    const d = path.join(scratch, 'mr-merge-gate-888-iiiiii')
    sh('git', ['worktree', 'add', '--detach', d, 'origin/main'], repo)
    const t = (Date.now() - 5 * HOUR) / 1000
    utimesSync(d, t, t)
    await sweepGateClones({ isAlive: dead, repoPath: repo })
    expect(existsSync(d)).toBe(false)
    expect(sh('git', ['worktree', 'list'], repo)).not.toContain('mr-merge-gate-888')
  })

  it('a missing temp folder is nothing to do', async () => {
    const r = await sweepGateClones({ root: path.join(root, 'nope'), repoPath: null })
    expect(r.removed).toEqual([])
  })

  it('the webhook runs the sweep when it starts', () => {
    const here = path.dirname(fileURLToPath(import.meta.url))
    const src = readFileSync(path.join(here, '..', 'webhook-server', 'index.js'), 'utf-8')
    const listen = src.slice(src.indexOf('server.listen('))
    expect(listen).toMatch(/sweepGateClones\(/)
  })
})
