import { describe, it, expect, vi } from 'vitest'
import { promisify } from 'util'
import { execFile, execFileSync } from 'child_process'
import { mkdtempSync, rmSync, writeFileSync, readFileSync } from 'fs'
import { tmpdir } from 'os'
import path from 'path'
import { bumpType, bumpVersion, formatChangelogEntry, applyVersionBump } from '../webhook-server/changelog.js'

const realExec = promisify(execFile)

function sh(cmd, args, cwd) {
  return execFileSync(cmd, args, { cwd, encoding: 'utf-8' })
}

function makeGitFixture() {
  const root = mkdtempSync(path.join(tmpdir(), 'changelog-fixture-'))
  const originDir = path.join(root, 'origin.git')
  const repoDir = path.join(root, 'repo')
  sh('git', ['init', '--quiet', '--bare', originDir])
  sh('git', ['clone', '--quiet', originDir, repoDir])
  sh('git', ['config', 'user.email', 'test@test.com'], repoDir)
  sh('git', ['config', 'user.name', 'Test'], repoDir)
  writeFileSync(path.join(repoDir, 'README.md'), 'hello\n')
  sh('git', ['add', '.'], repoDir)
  sh('git', ['commit', '-q', '-m', 'init'], repoDir)
  sh('git', ['branch', '-M', 'main'], repoDir)
  sh('git', ['push', '-u', 'origin', 'main'], repoDir)
  return { root, repoDir }
}

describe('bumpType', () => {
  it('returns "major" for breaking-change label', () => {
    expect(bumpType([{ name: 'breaking-change' }])).toBe('major')
  })

  it('returns "minor" for enhancement label', () => {
    expect(bumpType([{ name: 'enhancement' }])).toBe('minor')
  })

  it('returns "patch" for other labels', () => {
    expect(bumpType([{ name: 'bug' }])).toBe('patch')
  })

  it('returns "patch" for empty labels', () => {
    expect(bumpType([])).toBe('patch')
  })

  it('returns "patch" for undefined labels', () => {
    expect(bumpType(undefined)).toBe('patch')
  })

  it('prefers breaking-change over enhancement when both are present', () => {
    expect(bumpType([
      { name: 'enhancement' },
      { name: 'breaking-change' }
    ])).toBe('major')
  })

  it('prefers enhancement over bug when both are present', () => {
    expect(bumpType([
      { name: 'bug' },
      { name: 'enhancement' }
    ])).toBe('minor')
  })
})

describe('bumpVersion', () => {
  it('bumps major version (X.0.0)', () => {
    expect(bumpVersion('0.0.0', 'major')).toBe('1.0.0')
    expect(bumpVersion('1.2.3', 'major')).toBe('2.0.0')
  })

  it('bumps minor version (0.X.0)', () => {
    expect(bumpVersion('0.0.0', 'minor')).toBe('0.1.0')
    expect(bumpVersion('1.2.3', 'minor')).toBe('1.3.0')
  })

  it('bumps patch version (0.0.X)', () => {
    expect(bumpVersion('0.0.0', 'patch')).toBe('0.0.1')
    expect(bumpVersion('1.2.3', 'patch')).toBe('1.2.4')
  })

  it('rejects malformed version strings', () => {
    expect(() => bumpVersion('1.2', 'patch')).toThrow()
    expect(() => bumpVersion('1.2.3.4', 'patch')).toThrow()
    expect(() => bumpVersion('a.b.c', 'patch')).toThrow()
    expect(() => bumpVersion('1.2.3\n', 'patch')).toThrow()
  })

  it('rejects invalid bump types', () => {
    expect(() => bumpVersion('1.2.3', 'invalid')).toThrow()
  })
})

describe('formatChangelogEntry', () => {
  it('formats a changelog entry as a markdown bullet with link', () => {
    const entry = formatChangelogEntry('Fix memory leak in dashboard', 'https://github.com/G-Eskayo/marvin/pull/123')
    expect(entry).toBe('- Fix memory leak in dashboard ([#123](https://github.com/G-Eskayo/marvin/pull/123))')
  })

  it('preserves special markdown characters in the title', () => {
    const entry = formatChangelogEntry('Add `async` support to CLI', 'https://github.com/G-Eskayo/marvin/pull/124')
    expect(entry).toContain('Add `async` support to CLI')
  })

  it('handles titles with URLs and brackets', () => {
    const entry = formatChangelogEntry('See [docs](https://example.com) for details', 'https://github.com/G-Eskayo/marvin/pull/125')
    expect(entry).toContain('#125')
  })

  it('handles titles with embedded newlines by rejecting them', () => {
    expect(() => formatChangelogEntry('Title\nwith\nnewlines', 'https://github.com/G-Eskayo/marvin/pull/126')).toThrow()
  })

  it('extracts PR number from the URL correctly', () => {
    const entry = formatChangelogEntry('Update versioning system', 'https://github.com/G-Eskayo/marvin/pull/299')
    expect(entry).toContain('#299')
  })
})

describe('applyVersionBump', () => {
  it('creates VERSION and CHANGELOG.md files with initial bump', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      const mockGh = vi.fn(async (cmd, args, ...rest) => {
        if (args[0] === 'issue' && args[1] === 'view') {
          return { stdout: JSON.stringify({ labels: [{ name: 'enhancement' }], title: 'Add new feature' }), stderr: '' }
        }
        return realExec(cmd, args, ...rest)
      })

      await applyVersionBump(
        { ticketNumber: 5, prUrl: 'https://github.com/G-Eskayo/marvin/pull/99' },
        mockGh,
        repoDir
      )

      sh('git', ['fetch', 'origin', 'main'], repoDir)
      const versionContent = sh('git', ['show', 'origin/main:VERSION'], repoDir).trim()
      const changelogContent = sh('git', ['show', 'origin/main:CHANGELOG.md'], repoDir)

      expect(versionContent).toBe('0.1.0')
      expect(changelogContent).toContain('# Changelog')
      expect(changelogContent).toContain('Add new feature')
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('bumps version correctly from existing VERSION file', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'VERSION'), '1.2.3\n')
      writeFileSync(path.join(repoDir, 'CHANGELOG.md'), '# Changelog\n\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'init versioning'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      const mockGh = vi.fn(async (cmd, args, ...rest) => {
        if (args[0] === 'issue' && args[1] === 'view') {
          return { stdout: JSON.stringify({ labels: [{ name: 'breaking-change' }], title: 'Major API change' }), stderr: '' }
        }
        return realExec(cmd, args, ...rest)
      })

      await applyVersionBump(
        { ticketNumber: 6, prUrl: 'https://github.com/G-Eskayo/marvin/pull/100' },
        mockGh,
        repoDir
      )

      sh('git', ['fetch', 'origin', 'main'], repoDir)
      const versionContent = sh('git', ['show', 'origin/main:VERSION'], repoDir).trim()

      expect(versionContent).toBe('2.0.0')
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('skips versioning when PR URL already in CHANGELOG.md (idempotency)', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'VERSION'), '0.5.0\n')
      writeFileSync(path.join(repoDir, 'CHANGELOG.md'), '# Changelog\n\n- Existing entry ([#99](https://github.com/G-Eskayo/marvin/pull/99))\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'init'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      const mockGh = vi.fn(async (cmd, args, ...rest) => {
        if (cmd === 'gh' && args[0] === 'issue' && args[1] === 'view') {
          throw new Error('Should not fetch issue when already in changelog')
        }
        return realExec(cmd, args, ...rest)
      })

      await applyVersionBump(
        { ticketNumber: 7, prUrl: 'https://github.com/G-Eskayo/marvin/pull/99' },
        mockGh,
        repoDir
      )

      sh('git', ['fetch', 'origin', 'main'], repoDir)
      const versionContent = sh('git', ['show', 'origin/main:VERSION'], repoDir).trim()

      expect(versionContent).toBe('0.5.0')
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('handles malformed CHANGELOG heading by inserting after the heading line', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'VERSION'), '1.0.0\n')
      writeFileSync(path.join(repoDir, 'CHANGELOG.md'), '# Changelog\n\nSome content without proper spacing\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'init'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      const mockGh = vi.fn(async (cmd, args, ...rest) => {
        if (args[0] === 'issue' && args[1] === 'view') {
          return { stdout: JSON.stringify({ labels: [], title: 'Bug fix' }), stderr: '' }
        }
        return realExec(cmd, args, ...rest)
      })

      await applyVersionBump(
        { ticketNumber: 8, prUrl: 'https://github.com/G-Eskayo/marvin/pull/101' },
        mockGh,
        repoDir
      )

      sh('git', ['fetch', 'origin', 'main'], repoDir)
      const changelogContent = sh('git', ['show', 'origin/main:CHANGELOG.md'], repoDir)
      const versionContent = sh('git', ['show', 'origin/main:VERSION'], repoDir).trim()

      expect(versionContent).toBe('1.0.1')
      expect(changelogContent).toContain('Bug fix')
      expect(changelogContent).toMatch(/# Changelog[\s\S]*Bug fix/)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('retries push on non-fast-forward conflict', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'VERSION'), '1.0.0\n')
      writeFileSync(path.join(repoDir, 'CHANGELOG.md'), '# Changelog\n\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'init'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      let pushAttempts = 0
      const flakyExec = vi.fn(async (cmd, args, opts) => {
        if (cmd === 'git' && args[0] === 'push' && pushAttempts++ < 1) {
          throw Object.assign(new Error('non-fast-forward'), { stderr: 'remote: non-fast-forward' })
        }
        if (cmd === 'gh' && args[0] === 'issue' && args[1] === 'view') {
          return { stdout: JSON.stringify({ labels: [], title: 'Test entry' }), stderr: '' }
        }
        return realExec(cmd, args, opts)
      })

      await applyVersionBump(
        { ticketNumber: 9, prUrl: 'https://github.com/G-Eskayo/marvin/pull/102' },
        flakyExec,
        repoDir
      )

      sh('git', ['fetch', 'origin', 'main'], repoDir)
      const versionContent = sh('git', ['show', 'origin/main:VERSION'], repoDir).trim()

      expect(versionContent).toBe('1.0.1')
      expect(pushAttempts).toBe(2)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('fails after bounded retry attempts on persistent push failure', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'VERSION'), '1.0.0\n')
      writeFileSync(path.join(repoDir, 'CHANGELOG.md'), '# Changelog\n\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'init'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      const flakyExec = vi.fn(async (cmd, args, ...rest) => {
        if (cmd === 'git' && args[0] === 'push') {
          throw new Error('persistent failure')
        }
        if (cmd === 'gh' && args[0] === 'issue' && args[1] === 'view') {
          return { stdout: JSON.stringify({ labels: [], title: 'Test' }), stderr: '' }
        }
        return realExec(cmd, args, ...rest)
      })

      await expect(applyVersionBump(
        { ticketNumber: 10, prUrl: 'https://github.com/G-Eskayo/marvin/pull/103' },
        flakyExec,
        repoDir
      )).rejects.toThrow()
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('handles corrupted VERSION file by failing cleanly', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'VERSION'), 'not-a-version\n')
      writeFileSync(path.join(repoDir, 'CHANGELOG.md'), '# Changelog\n\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'init'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      const mockGh = vi.fn(async (cmd, args, ...rest) => {
        if (args[0] === 'issue' && args[1] === 'view') {
          return { stdout: JSON.stringify({ labels: [], title: 'Test' }), stderr: '' }
        }
        return realExec(cmd, args, ...rest)
      })

      await expect(applyVersionBump(
        { ticketNumber: 11, prUrl: 'https://github.com/G-Eskayo/marvin/pull/104' },
        mockGh,
        repoDir
      )).rejects.toThrow()
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('enforces cwd on all git/gh operations (harness self-defense)', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'VERSION'), '1.0.0\n')
      writeFileSync(path.join(repoDir, 'CHANGELOG.md'), '# Changelog\n\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'init'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      const undefinedCwds = []
      const cwdTracker = vi.fn(async (cmd, args, opts) => {
        // Track any calls where cwd is undefined
        if (cmd === 'git' && opts?.cwd === undefined) {
          undefinedCwds.push(`${cmd} ${args[0]}`)
        }

        if (cmd === 'gh' && args[0] === 'issue' && args[1] === 'view') {
          return { stdout: JSON.stringify({ labels: [], title: 'Test' }), stderr: '' }
        }
        return realExec(cmd, args, opts)
      })

      await applyVersionBump(
        { ticketNumber: 12, prUrl: 'https://github.com/G-Eskayo/marvin/pull/105' },
        cwdTracker,
        repoDir
      )

      // Assert that no git operations had undefined cwd
      expect(undefinedCwds).toEqual([])
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('cleans up worktree even when creation fails', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'VERSION'), '1.0.0\n')
      writeFileSync(path.join(repoDir, 'CHANGELOG.md'), '# Changelog\n\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'init'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      let cleanupCalls = 0
      const failOnWorktreeAdd = vi.fn(async (cmd, args, opts) => {
        if (cmd === 'git' && args[0] === 'worktree' && args[1] === 'add') {
          throw new Error('simulated worktree creation failure')
        }
        if (cmd === 'git' && args[0] === 'worktree' && args[1] === 'remove') {
          cleanupCalls++
        }
        if (cmd === 'gh' && args[0] === 'issue' && args[1] === 'view') {
          return { stdout: JSON.stringify({ labels: [], title: 'Test' }), stderr: '' }
        }
        return realExec(cmd, args, opts)
      })

      await expect(applyVersionBump(
        { ticketNumber: 13, prUrl: 'https://github.com/G-Eskayo/marvin/pull/106' },
        failOnWorktreeAdd,
        repoDir
      )).rejects.toThrow('worktree creation failure')

      // Cleanup should have been attempted (even though worktree creation failed)
      expect(cleanupCalls).toBeGreaterThan(0)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('returns cleanly when PR already in changelog (crash-and-retry safety)', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'VERSION'), '1.5.0\n')
      writeFileSync(path.join(repoDir, 'CHANGELOG.md'), '# Changelog\n\n- Previous work ([#107](https://github.com/G-Eskayo/marvin/pull/107))\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'init'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      let ghCallCount = 0
      const spy = vi.fn(async (cmd, args, opts) => {
        if (cmd === 'gh' && args[0] === 'issue' && args[1] === 'view') {
          ghCallCount++
          return { stdout: JSON.stringify({ labels: [], title: 'Test' }), stderr: '' }
        }
        return realExec(cmd, args, opts)
      })

      // Call with a PR URL that's already in the changelog
      await applyVersionBump(
        { ticketNumber: 14, prUrl: 'https://github.com/G-Eskayo/marvin/pull/107' },
        spy,
        repoDir
      )

      // gh issue view should never have been called (early exit via idempotency guard)
      expect(ghCallCount).toBe(0)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })

  it('re-reads VERSION from fresh state on each retry attempt', async () => {
    const { root, repoDir } = makeGitFixture()
    try {
      writeFileSync(path.join(repoDir, 'VERSION'), '1.0.0\n')
      writeFileSync(path.join(repoDir, 'CHANGELOG.md'), '# Changelog\n\n')
      sh('git', ['add', '.'], repoDir)
      sh('git', ['commit', '-q', '-m', 'init'], repoDir)
      sh('git', ['push', 'origin', 'main'], repoDir)

      let pushAttempts = 0
      let versionReads = []

      const replayExec = vi.fn(async (cmd, args, opts) => {
        if (cmd === 'git' && args[0] === 'show' && args[1].includes('VERSION')) {
          const result = await realExec(cmd, args, opts)
          versionReads.push(result.stdout.trim())
          return result
        }
        if (cmd === 'git' && args[0] === 'push' && pushAttempts++ < 1) {
          throw Object.assign(new Error('non-fast-forward'), { stderr: 'remote: non-fast-forward' })
        }
        if (cmd === 'gh' && args[0] === 'issue' && args[1] === 'view') {
          return { stdout: JSON.stringify({ labels: [{ name: 'patch' }], title: 'Bug fix' }), stderr: '' }
        }
        return realExec(cmd, args, opts)
      })

      await applyVersionBump(
        { ticketNumber: 15, prUrl: 'https://github.com/G-Eskayo/marvin/pull/108' },
        replayExec,
        repoDir
      )

      // Should have read VERSION at least twice (once early, once per retry loop)
      expect(versionReads.length).toBeGreaterThanOrEqual(2)
    } finally {
      rmSync(root, { recursive: true, force: true })
    }
  })
})
