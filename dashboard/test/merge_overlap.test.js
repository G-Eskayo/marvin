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
