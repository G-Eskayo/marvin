import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { execFileSync } from 'child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { sharedFiles, conflictsWithBase, execWithGroupTimeout } from '../webhook-server/merge.js'

// A real origin + clone: main gains commits after each branch splits off.
let dir, clone
const git = (cwd, ...args) => execFileSync('git', args, { cwd, stdio: 'pipe' }).toString()
const commit = (file, text, msg) => { writeFileSync(path.join(clone, file), text); git(clone, 'add', file); git(clone, 'commit', '-qm', msg) }

beforeAll(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'overlap-'))
  const origin = path.join(dir, 'origin.git')
  clone = path.join(dir, 'clone')
  git(dir, 'init', '-q', '--bare', '-b', 'main', origin)
  git(dir, 'clone', '-q', origin, clone)
  git(clone, 'config', 'user.email', 't@t'); git(clone, 'config', 'user.name', 't')
  commit('a.txt', 'a\n', 'base a'); commit('b.txt', 'b\n', 'base b'); commit('c.txt', 'c1\nc2\nc3\n', 'base c')
  git(clone, 'push', '-q', 'origin', 'main')
  // three PR branches from the same base
  git(clone, 'checkout', '-qb', 'pr-separate'); commit('b.txt', 'b changed by pr\n', 'pr touches b'); git(clone, 'push', '-q', 'origin', 'pr-separate')
  git(clone, 'checkout', '-q', 'main'); git(clone, 'checkout', '-qb', 'pr-shared'); commit('c.txt', 'c1\nc2\nc3 pr\n', 'pr touches c line 3'); git(clone, 'push', '-q', 'origin', 'pr-shared')
  git(clone, 'checkout', '-q', 'main'); git(clone, 'checkout', '-qb', 'pr-conflict'); commit('a.txt', 'a by pr\n', 'pr rewrites a'); git(clone, 'push', '-q', 'origin', 'pr-conflict')
  // main moves on: rewrites a (conflicts with pr-conflict), edits c line 1 (same file as pr-shared, no conflict)
  git(clone, 'checkout', '-q', 'main'); commit('a.txt', 'a by main\n', 'main rewrites a'); commit('c.txt', 'c1 main\nc2\nc3\n', 'main edits c line 1')
  git(clone, 'push', '-q', 'origin', 'main')
})
afterAll(() => rmSync(dir, { recursive: true, force: true }))

describe('sharedFiles: does main touch anything this PR touches, since they split?', () => {
  it('none when main changed other files: merge without a retest', async () => {
    expect(await sharedFiles('pr-separate', execWithGroupTimeout, clone, 'main')).toEqual([])
  })
  it('names the files both changed', async () => {
    expect(await sharedFiles('pr-shared', execWithGroupTimeout, clone, 'main')).toEqual(['c.txt'])
    expect(await sharedFiles('pr-conflict', execWithGroupTimeout, clone, 'main')).toEqual(['a.txt'])
  })
})

describe('conflictsWithBase: would the PR still merge, without checking anything out or running tests?', () => {
  it('no conflict, including a shared file edited in different places', async () => {
    expect(await conflictsWithBase('pr-separate', execWithGroupTimeout, clone, 'main')).toEqual({ conflict: false, files: [] })
    expect(await conflictsWithBase('pr-shared', execWithGroupTimeout, clone, 'main')).toEqual({ conflict: false, files: [] })
  })
  it('a real conflict, with its files', async () => {
    expect(await conflictsWithBase('pr-conflict', execWithGroupTimeout, clone, 'main')).toEqual({ conflict: true, files: ['a.txt'] })
  })
  it('a git failure is an error, not a conflict', async () => {
    await expect(conflictsWithBase('no-such-branch', execWithGroupTimeout, clone, 'main')).rejects.toThrow()
  })
})

import { defaultShouldGateMerge } from '../webhook-server/merge.js'

describe('defaultShouldGateMerge: retest only a PR that is behind AND shares files with what main changed', () => {
  const execFor = (head) => async (cmd, args, opts) => {
    if (cmd === 'gh') return { stdout: JSON.stringify({ headRefName: head, body: 'Closes G-Eskayo/marvin#1' }), stderr: '' }
    return execWithGroupTimeout(cmd, args, opts)
  }
  const ctx = () => ({ clone, base: 'main' })

  it('behind but no shared files: merge directly, and say so', async () => {
    const d = await defaultShouldGateMerge('https://github.com/o/r/pull/1', execFor('pr-separate'), ctx())
    expect(d).toMatchObject({ gate: false, behind: true, shared: [] })
  })

  it('behind and sharing a file: retest', async () => {
    const d = await defaultShouldGateMerge('https://github.com/o/r/pull/2', execFor('pr-shared'), ctx())
    expect(d).toMatchObject({ gate: true, behind: true, shared: ['c.txt'] })
  })

  it('cannot tell what overlaps: retest, to be safe', async () => {
    const exec = async (cmd, args, opts) => {
      if (cmd === 'gh') return { stdout: JSON.stringify({ headRefName: 'pr-shared', body: '' }), stderr: '' }
      if (args[0] === 'diff') throw new Error('git diff broke')
      return execWithGroupTimeout(cmd, args, opts)
    }
    expect((await defaultShouldGateMerge('https://github.com/o/r/pull/3', exec, ctx())).gate).toBe(true)
  })
})

// 2026-10-26: PR #572 was tested on 10-21; main then gained test_instance_move.py (ADR 0071). Main changed none of
// #572's files, so it merged without a retest and broke main. A new rule on main must judge older PRs before they land.
import { mainChanges, RULE_FILE } from '../webhook-server/merge.js'

describe('a rule main gained since the PR split forces a retest, even with no shared files', () => {
  let rdir, rclone
  const rcommit = (file, text, msg) => {
    const p = path.join(rclone, file)
    execFileSync('mkdir', ['-p', path.dirname(p)])
    writeFileSync(p, text); git(rclone, 'add', file); git(rclone, 'commit', '-qm', msg)
  }
  const execFor = (head) => async (cmd, args, opts) => {
    if (cmd === 'gh') return { stdout: JSON.stringify({ headRefName: head, body: '' }), stderr: '' }
    return execWithGroupTimeout(cmd, args, opts)
  }
  beforeAll(() => {
    rdir = mkdtempSync(path.join(tmpdir(), 'rules-'))
    const origin = path.join(rdir, 'origin.git')
    rclone = path.join(rdir, 'clone')
    git(rdir, 'init', '-q', '--bare', '-b', 'main', origin)
    git(rdir, 'clone', '-q', origin, rclone)
    git(rclone, 'config', 'user.email', 't@t'); git(rclone, 'config', 'user.name', 't')
    rcommit('app.py', 'x = 1\n', 'base'); git(rclone, 'push', '-q', 'origin', 'main')
    for (const b of ['pr-doc', 'pr-code-only']) {
      git(rclone, 'checkout', '-q', 'main'); git(rclone, 'checkout', '-qb', b); rcommit(`docs/${b}.md`, 'doc\n', b); git(rclone, 'push', '-q', 'origin', b)
    }
    git(rclone, 'checkout', '-q', 'main')
    rcommit('lib/other.py', 'y = 2\n', 'main changes code only'); git(rclone, 'push', '-q', 'origin', 'main')
    git(rclone, 'checkout', '-q', 'pr-code-only'); git(rclone, 'merge', '-q', '--no-edit', 'main'); git(rclone, 'push', '-q', 'origin', 'pr-code-only')
    git(rclone, 'checkout', '-q', 'main')
    rcommit('lib/other2.py', 'z = 3\n', 'more code'); git(rclone, 'push', '-q', 'origin', 'main')
    git(rclone, 'checkout', '-q', 'main'); git(rclone, 'checkout', '-qb', 'main-rule')
    rcommit('lib/tests/test_instance_move.py', 'def test_x(): pass\n', 'main gains a rule'); git(rclone, 'push', '-q', 'origin', 'main-rule:main')
  })
  afterAll(() => rmSync(rdir, { recursive: true, force: true, maxRetries: 5, retryDelay: 50 }))

  it('main added a test since the PR split: retest, and name the rule', async () => {
    const d = await defaultShouldGateMerge('https://github.com/o/r/pull/9', execFor('pr-doc'), { clone: rclone, base: 'main' })
    expect(d).toMatchObject({ gate: true, behind: true, shared: [], rules: ['lib/tests/test_instance_move.py'] })
  })

  it('only test and guard files count as rules: code main changed since the split does not', async () => {
    // pr-code-only split after 'main changes code only'; since then main added lib/other2.py (code) and the rule
    const m = await mainChanges('pr-code-only', execWithGroupTimeout, rclone, 'main')
    expect(m).toEqual({ shared: [], rules: ['lib/tests/test_instance_move.py'] })
  })

  it('which paths count as rules, and lookalikes that do not', () => {
    for (const p of ['lib/tests/test_x.py', 'test_top.py', 'skills/a/scripts/tests/test_b.py', 'dashboard/test/merge.test.js',
      'src/x.test.jsx', 'conftest.py', 'lib/conftest.py', 'pytest.ini', 'config/push-guard/paths.txt', '.gitignore',
      'dashboard/test/polling_guard.js']) expect([p, RULE_FILE.test(p)]).toEqual([p, true])
    for (const p of ['latest.md', 'lib/contest.py', 'docs/testing.md', 'lib/attest.py', 'config/push-guard.md', 'src/protest.js',
      'lib/test_helpers_notes.md']) expect([p, RULE_FILE.test(p)]).toEqual([p, false])
  })

  it('a git failure while reading main\'s changes: retest, to be safe', async () => {
    const exec = async (cmd, args, opts) => {
      if (cmd === 'gh') return { stdout: JSON.stringify({ headRefName: 'pr-doc', body: '' }), stderr: '' }
      if (args[0] === 'diff') throw new Error('git diff broke')
      return execWithGroupTimeout(cmd, args, opts)
    }
    expect((await defaultShouldGateMerge('https://github.com/o/r/pull/10', exec, { clone: rclone, base: 'main' })).gate).toBe(true)
  })
})
