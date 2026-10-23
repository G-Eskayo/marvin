// #611 part 2: clean local clones are fast-forwarded in the background; a clone that is mid-work is never touched.
// Every case is a real git repo with a bare origin in a temp dir (and a temp HOME, so ~/.agents is a temp path).
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, readFileSync, existsSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { execFileSync, execFile } from 'child_process'
import { promisify } from 'util'
import { cloneState, createCloneFreshener } from '../electron/main/clone_freshen.js'

const run = promisify(execFile)
const exec = (cmd, args, opts) => run(cmd, args, opts)
let root
let home
const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8', env: { ...process.env, HOME: home, GIT_CONFIG_NOSYSTEM: '1' } }).trim()

function setup() {
  const origin = path.join(root, 'origin.git')
  git(root, 'init', '-q', '--bare', '-b', 'main', origin)
  const seed = path.join(root, 'seed')
  git(root, 'clone', '-q', origin, seed)
  mkdirSync(path.join(seed, 'docs'), { recursive: true })
  writeFileSync(path.join(seed, 'docs', 'a.md'), '# A\n')
  git(seed, 'add', '.')
  git(seed, 'commit', '-q', '-m', 'one')
  git(seed, 'push', '-q', 'origin', 'main')
  const clone = path.join(root, 'clone')
  git(root, 'clone', '-q', origin, clone)
  return { origin, seed, clone }
}
// The seed pushes a new doc, so the clone is one commit behind origin.
function pushNew(seed, name = 'parakeet.md', text = '# Parakeet\n') {
  writeFileSync(path.join(seed, 'docs', name), text)
  git(seed, 'add', '.')
  git(seed, 'commit', '-q', '-m', `add ${name}`)
  git(seed, 'push', '-q', 'origin', 'main')
}
const head = (dir) => git(dir, 'rev-parse', 'HEAD')

beforeEach(() => {
  root = mkdtempSync(path.join(tmpdir(), 'freshen-'))
  home = path.join(root, 'home')
  mkdirSync(home)
  git(root, 'config', '--global', 'user.email', 't@t')
  git(root, 'config', '--global', 'user.name', 't')
  git(root, 'config', '--global', 'init.defaultBranch', 'main')
})
afterEach(() => rmSync(root, { recursive: true, force: true }))

const envExec = (cmd, args, opts = {}) => exec(cmd, args, { ...opts, env: { ...process.env, HOME: home, GIT_CONFIG_NOSYSTEM: '1' } })

describe('cloneState', () => {
  it('a clean clone behind origin is clean-behind, after a fetch', async () => {
    const { seed, clone } = setup()
    pushNew(seed)
    git(clone, 'fetch', '-q')
    expect((await cloneState(clone, envExec)).status).toBe('behind')
  })

  it('a clean, current clone is current', async () => {
    const { clone } = setup()
    expect((await cloneState(clone, envExec)).status).toBe('current')
  })

  it('an unstaged edit, a staged edit or an untracked file is dirty', async () => {
    const { clone } = setup()
    writeFileSync(path.join(clone, 'docs', 'a.md'), '# A edited\n')
    expect((await cloneState(clone, envExec)).status).toBe('dirty')
    git(clone, 'add', '.')
    expect((await cloneState(clone, envExec)).status).toBe('dirty')
    git(clone, 'reset', '-q', '--hard')
    writeFileSync(path.join(clone, 'notes.md'), 'draft\n')
    expect((await cloneState(clone, envExec)).status).toBe('dirty')
  })

  it("untracked files under .claude/ (agent worktrees, settings) don't count", async () => {
    const { clone } = setup()
    mkdirSync(path.join(clone, '.claude', 'worktrees', 'x'), { recursive: true })
    writeFileSync(path.join(clone, '.claude', 'worktrees', 'x', 'f'), 'x')
    expect((await cloneState(clone, envExec)).status).toBe('current')
  })

  it('a clone on another branch is other-branch', async () => {
    const { clone } = setup()
    git(clone, 'checkout', '-q', '-b', 'feature/x')
    expect((await cloneState(clone, envExec)).status).toBe('other-branch')
  })

  it('a clone with a local commit is ahead; with origin moved too it is diverged', async () => {
    const { seed, clone } = setup()
    writeFileSync(path.join(clone, 'docs', 'mine.md'), '# Mine\n')
    git(clone, 'add', '.')
    git(clone, 'commit', '-q', '-m', 'mine')
    expect((await cloneState(clone, envExec)).status).toBe('ahead')
    pushNew(seed)
    git(clone, 'fetch', '-q')
    expect((await cloneState(clone, envExec)).status).toBe('diverged')
  })

  it('a clone mid-rebase is mid-operation, even with a clean-looking tree', async () => {
    const { seed, clone } = setup()
    writeFileSync(path.join(clone, 'docs', 'a.md'), '# A mine\n')
    git(clone, 'commit', '-q', '-am', 'mine')
    pushNew(seed, 'a.md', '# A theirs\n')
    git(clone, 'fetch', '-q')
    try {
      git(clone, 'rebase', 'origin/main')
    } catch {
      // conflict: the rebase stops half-way, as it does for a person
    }
    git(clone, 'checkout', '--theirs', '.') // even after resolving the files, the rebase is still in progress
    git(clone, 'add', '.')
    expect((await cloneState(clone, envExec)).status).toBe('mid-operation')
  })

  it('a git worktree (.git is a file) is a worktree', async () => {
    const { clone } = setup()
    const wt = path.join(root, 'wt')
    git(clone, 'worktree', 'add', '-q', wt, '-b', 'wt-branch')
    expect((await cloneState(wt, envExec)).status).toBe('worktree')
  })
})

describe('createCloneFreshener', () => {
  const projects = (dir, extra = {}) => [{ id: 'p', repo: 'G-Eskayo/p', localPaths: [dir], ...extra }]
  const make = (o = {}) => {
    o = { openInXcode: async () => false, ...o }
    const log = path.join(home, '.agents', 'var', 'clone-freshen.jsonl')
    let t = 1_000_000
    const f = createCloneFreshener({ exec: envExec, home, logPath: log, now: () => t, minIntervalMs: 30 * 60 * 1000, ...o })
    return { f, log, advance: (ms) => (t += ms) }
  }

  it('clean-behind: fetches and fast-forwards, logs it, and reports the change', async () => {
    const { seed, clone } = setup()
    pushNew(seed)
    const { f, log } = make()
    const r = await f.freshen(projects(clone))
    expect(head(clone)).toBe(head(seed))
    expect(existsSync(path.join(clone, 'docs', 'parakeet.md'))).toBe(true)
    expect(r.updated).toEqual(['p'])
    const line = JSON.parse(readFileSync(log, 'utf8').trim().split('\n').at(-1))
    expect(line).toMatchObject({ project: 'p', result: 'fast-forwarded' })
    expect(f.midWork(clone)).toBe(false)
  })

  for (const [name, prep] of [
    ['dirty', (c) => writeFileSync(path.join(c, 'docs', 'a.md'), '# edited, not committed\n')],
    ['other branch', (c) => git(c, 'checkout', '-q', '-b', 'feature/x')],
    ['ahead', (c) => (writeFileSync(path.join(c, 'docs', 'm.md'), 'm'), git(c, 'add', '.'), git(c, 'commit', '-q', '-m', 'm'))]
  ]) {
    it(`${name}: never moves HEAD, never touches files, and marks the clone mid-work`, async () => {
      const { seed, clone } = setup()
      prep(clone)
      pushNew(seed)
      const before = head(clone)
      const status = git(clone, 'status', '--porcelain')
      const { f } = make()
      const r = await f.freshen(projects(clone))
      expect(head(clone)).toBe(before)
      expect(git(clone, 'status', '--porcelain')).toBe(status)
      expect(r.updated).toEqual([])
      expect(r.midWork).toEqual(['p'])
      expect(f.midWork(clone)).toBe(true)
    })
  }

  it('diverged: left alone (no merge commit, no reset)', async () => {
    const { seed, clone } = setup()
    writeFileSync(path.join(clone, 'docs', 'm.md'), 'm')
    git(clone, 'add', '.')
    git(clone, 'commit', '-q', '-m', 'm')
    pushNew(seed)
    git(clone, 'fetch', '-q')
    const before = head(clone)
    const { f } = make()
    await f.freshen(projects(clone))
    expect(head(clone)).toBe(before)
    expect(git(clone, 'rev-list', '--count', 'HEAD')).toBe('2')
    expect(f.midWork(clone)).toBe(true)
  })

  it('never touches the shared ~/.agents checkout, even when it is clean and behind', async () => {
    const { seed, origin } = setup()
    const agents = path.join(home, '.agents')
    git(root, 'clone', '-q', origin, agents)
    pushNew(seed)
    const before = head(agents)
    const { f } = make()
    const r = await f.freshen(projects(agents))
    expect(head(agents)).toBe(before)
    expect(r.updated).toEqual([])
    expect(f.midWork(agents)).toBe(false) // auto-sync owns it: still searched from disk
  })

  it('never touches a worktree', async () => {
    const { seed, clone } = setup()
    const wt = path.join(root, 'wt')
    git(clone, 'worktree', 'add', '-q', wt, 'origin/main', '--detach')
    pushNew(seed)
    const before = head(wt)
    const { f } = make()
    await f.freshen(projects(wt))
    expect(head(wt)).toBe(before)
  })

  it('runs at most once per project per interval; a second call inside it does nothing', async () => {
    const { seed, clone } = setup()
    const calls = []
    const counting = (cmd, args, opts) => (calls.push(args.join(' ')), envExec(cmd, args, opts))
    const { f, advance } = make({ exec: counting })
    await f.freshen(projects(clone))
    const n = calls.length
    pushNew(seed)
    await f.freshen(projects(clone))
    expect(calls.length).toBe(n)
    advance(31 * 60 * 1000)
    const r = await f.freshen(projects(clone))
    expect(r.updated).toEqual(['p'])
  })

  it('two overlapping calls run the work once', async () => {
    const { seed, clone } = setup()
    pushNew(seed)
    const { f } = make()
    const [a, b] = await Promise.all([f.freshen(projects(clone)), f.freshen(projects(clone))])
    expect([...a.updated, ...b.updated]).toEqual(['p'])
  })

  it('a fetch that fails (offline) leaves the clone as it was and does not throw', async () => {
    const { clone } = setup()
    git(clone, 'remote', 'set-url', 'origin', path.join(root, 'nowhere.git'))
    const before = head(clone)
    const { f, log } = make()
    const r = await f.freshen(projects(clone))
    expect(head(clone)).toBe(before)
    expect(r.updated).toEqual([])
    expect(readFileSync(log, 'utf8')).toContain('fetch-failed')
  })

  it('a clone open in Xcode is left alone, even clean and behind (Gil: never change a repo open in Xcode)', async () => {
    const { seed, clone } = setup()
    pushNew(seed)
    const before = head(clone)
    const calls = []
    const counting = (cmd, args, opts) => (calls.push(args.join(' ')), envExec(cmd, args, opts))
    const { f, log } = make({ exec: counting, openInXcode: async (dir) => dir === clone })
    const r = await f.freshen(projects(clone))
    expect(head(clone)).toBe(before)
    expect(r.updated).toEqual([])
    expect(calls.some((c) => c.includes('fetch') || c.includes('merge'))).toBe(false)
    expect(readFileSync(log, 'utf8')).toContain('open-in-xcode')
  })

  it('when the Xcode check itself fails, the clone is left alone (fail closed)', async () => {
    const { seed, clone } = setup()
    pushNew(seed)
    const before = head(clone)
    const { f } = make({ openInXcode: async () => { throw new Error('lsof missing') } })
    await f.freshen(projects(clone))
    expect(head(clone)).toBe(before)
  })

  it('a project with no clone on this machine, or no repo, is skipped', async () => {
    const { f } = make()
    const r = await f.freshen([{ id: 'x', repo: 'G-Eskayo/x', localPaths: [path.join(root, 'missing')] }, { id: 'y', localPaths: [] }])
    expect(r.updated).toEqual([])
  })

  it('keeps the log bounded', async () => {
    const { clone } = setup()
    writeFileSync(path.join(clone, 'docs', 'a.md'), '# dirty: every look is logged\n')
    const { f, log, advance } = make({ maxLogLines: 5 })
    for (let i = 0; i < 9; i++) {
      await f.freshen(projects(clone))
      advance(31 * 60 * 1000)
    }
    expect(readFileSync(log, 'utf8').trim().split('\n').length).toBeLessThanOrEqual(5)
  })
})
