import { promisify } from 'util'
import { execFile } from 'child_process'
import { mkdtemp, rm, readFile, writeFile } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

const execFileAsync = promisify(execFile)

export function bumpType(labels) {
  if (!labels || !Array.isArray(labels)) return 'patch'
  if (labels.some(l => l.name === 'breaking-change')) return 'major'
  if (labels.some(l => l.name === 'enhancement')) return 'minor'
  return 'patch'
}

export function bumpVersion(version, bumpTypeStr) {
  if (!['major', 'minor', 'patch'].includes(bumpTypeStr)) {
    throw new Error(`Invalid bump type: ${bumpTypeStr}`)
  }

  const parts = String(version).split('.')
  if (parts.length !== 3 || !parts.every(p => /^\d+$/.test(p))) {
    throw new Error(`Invalid version string: ${version}`)
  }

  const [major, minor, patch] = parts.map(Number)
  if (bumpTypeStr === 'major') return `${major + 1}.0.0`
  if (bumpTypeStr === 'minor') return `${major}.${minor + 1}.0`
  return `${major}.${minor}.${patch + 1}`
}

export function formatChangelogEntry(title, prUrl) {
  if (typeof title !== 'string' || title.includes('\n')) {
    throw new Error('Title must be a single line')
  }

  const match = prUrl.match(/\/pull\/(\d+)$/)
  if (!match) throw new Error(`Invalid PR URL: ${prUrl}`)

  const prNumber = match[1]
  return `- ${title} ([#${prNumber}](${prUrl}))`
}

export async function applyVersionBump(
  { ticketNumber, prUrl },
  exec = execFileAsync,
  repoPath
) {
  // Extract PR number from URL
  const prMatch = prUrl.match(/\/pull\/(\d+)$/)
  if (!prMatch) throw new Error(`Invalid PR URL: ${prUrl}`)
  const prNumber = prMatch[1]

  let tmpDir = null
  try {
    // Check if this PR is already in CHANGELOG (idempotency guard) - do this first to avoid unnecessary gh calls
    let changelogContent = ''
    try {
      const result = await exec('git', ['show', 'origin/main:CHANGELOG.md'], { cwd: repoPath })
      changelogContent = result.stdout
    } catch {
      // CHANGELOG doesn't exist yet, which is fine
    }
    if (changelogContent.includes(prUrl)) {
      return // Already recorded, skip
    }

    // Fetch ticket labels and title
    const { stdout: issueJson } = await exec('gh', ['issue', 'view', String(ticketNumber), '--json', 'labels,title', '--repo', 'G-Eskayo/marvin'])
    const issue = JSON.parse(issueJson)
    const { labels, title } = issue

    const bumpType_value = bumpType(labels)
    const entry = formatChangelogEntry(title, prUrl)

    // Create a worktree for this bump operation
    tmpDir = await mkdtemp(path.join(tmpdir(), 'version-bump-'))

    // Retry loop: up to 3 attempts, retrying on non-fast-forward
    const MAX_ATTEMPTS = 3
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      const currentWorktreePath = path.join(tmpDir, `worktree-${attempt}`)
      try {
        // Fetch the latest main to get the current tip before creating the worktree
        await exec('git', ['fetch', 'origin', 'main'], { cwd: repoPath })

        // Create a fresh worktree from the fetched tip
        await exec('git', ['worktree', 'add', '--detach', currentWorktreePath, 'origin/main'], { cwd: repoPath })

        try {
          // Configure git in the worktree
          await exec('git', ['config', 'user.email', 'marvin@marvin.dev'], { cwd: currentWorktreePath })
          await exec('git', ['config', 'user.name', 'MARVIN'], { cwd: currentWorktreePath })

          // Re-read VERSION and CHANGELOG from the fresh tip
          let updatedVersion = '0.0.0'
          try {
            const { stdout: vContent } = await exec('git', ['show', 'origin/main:VERSION'], { cwd: repoPath })
            updatedVersion = vContent.trim()
          } catch {
            // Doesn't exist yet
          }

          let changelogContent_fresh = ''
          try {
            const result = await exec('git', ['show', 'origin/main:CHANGELOG.md'], { cwd: repoPath })
            changelogContent_fresh = result.stdout
          } catch {
            // Doesn't exist yet
          }

          // If the PR is now in the changelog (another process beat us), stop
          if (changelogContent_fresh.includes(prUrl)) {
            return
          }

          // Compute the bump from the fresh state
          const bumpedVersion = bumpVersion(updatedVersion, bumpType_value)

          // Update VERSION file
          await writeFile(path.join(currentWorktreePath, 'VERSION'), `${bumpedVersion}\n`)

          // Update CHANGELOG
          let changelogText = changelogContent_fresh || '# Changelog\n\n'
          const headingMatch = changelogText.match(/^# Changelog/m)
          if (!headingMatch) {
            throw new Error('CHANGELOG.md must contain a "# Changelog" heading')
          }

          const headingIndex = changelogText.indexOf(headingMatch[0]) + headingMatch[0].length
          const beforeHeading = changelogText.slice(0, headingIndex)
          const afterHeading = changelogText.slice(headingIndex)

          const changelogText_new = beforeHeading + '\n\n' + entry + afterHeading.replace(/^\n\n/, '\n\n')
          await writeFile(path.join(currentWorktreePath, 'CHANGELOG.md'), changelogText_new)

          // Stage, commit, and push
          await exec('git', ['add', 'VERSION', 'CHANGELOG.md'], { cwd: currentWorktreePath })
          await exec('git', ['commit', '-m', `Version ${bumpedVersion}`], { cwd: currentWorktreePath })
          await exec('git', ['push', 'origin', 'HEAD:main'], { cwd: currentWorktreePath })

          return // Success
        } finally {
          // Clean up the worktree
          await exec('git', ['worktree', 'remove', '--force', currentWorktreePath], { cwd: repoPath }).catch(() => {})
        }
      } catch (error) {
        // Clean up worktree for this attempt
        await exec('git', ['worktree', 'remove', '--force', currentWorktreePath], { cwd: repoPath }).catch(() => {})

        const isNonFastForward = error.stderr && error.stderr.includes('non-fast-forward')
        if (!isNonFastForward || attempt === MAX_ATTEMPTS) {
          throw error
        }
        // Otherwise, retry
      }
    }
  } finally {
    // Clean up temp directory
    if (tmpDir) {
      await rm(tmpDir, { recursive: true, force: true }).catch(() => {})
    }
  }
}
