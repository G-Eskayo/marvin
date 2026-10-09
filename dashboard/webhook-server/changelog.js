import { readFileSync, writeFileSync, existsSync } from 'fs'
import { mkdtemp, rm } from 'fs/promises'
import { tmpdir } from 'os'
import path from 'path'

// Determine version bump type based on issue labels.
// ADR 0028 rule: breaking-change → major, otherwise enhancement → minor, else patch.
export function bumpType(labels = []) {
  if (labels.includes('breaking-change')) return 'major'
  if (labels.includes('enhancement')) return 'minor'
  return 'patch'
}

// Parse and bump a semantic version string.
export function bumpVersion(currentVersion, bumpTypeStr) {
  const parts = currentVersion.split('.')
  if (parts.length !== 3 || !parts.every((p) => /^\d+$/.test(p))) {
    throw new Error(`Invalid version format: ${currentVersion} (expected MAJOR.MINOR.PATCH)`)
  }
  const [major, minor, patch] = parts.map(Number)

  if (bumpTypeStr === 'major') {
    return `${major + 1}.0.0`
  } else if (bumpTypeStr === 'minor') {
    return `${major}.${minor + 1}.0`
  } else if (bumpTypeStr === 'patch') {
    return `${major}.${minor}.${patch + 1}`
  }
  throw new Error(`Invalid bump type: ${bumpTypeStr}`)
}

// Format a single changelog entry as a markdown line.
export function formatChangelogEntry(version, title, prUrl, date) {
  const dateStr = date instanceof Date ? date.toISOString().split('T')[0] : date
  return `- ${title} ([PR](${prUrl}))`
}

// Fetch labels and title for a ticket, then apply version bump and record stage.
export async function applyVersionBump(
  { ticketNumber, repo, title, prUrl },
  exec,
  repoPath
) {
  // Fetch ticket metadata if not already provided
  let ticketTitle = title
  let labels = []

  if (!title) {
    const { stdout } = await exec('gh', ['issue', 'view', ticketNumber, '--repo', repo, '--json', 'labels,title'])
    const metadata = JSON.parse(stdout)
    ticketTitle = metadata.title
    labels = metadata.labels.map((l) => l.name)
  } else {
    // Still need labels; assume title was already fetched
    const { stdout } = await exec('gh', ['issue', 'view', ticketNumber, '--repo', repo, '--json', 'labels'])
    const metadata = JSON.parse(stdout)
    labels = metadata.labels.map((l) => l.name)
  }

  // Create scratch worktree
  const scratchDir = await mkdtemp(path.join(tmpdir(), 'marvin-version-'))
  try {
    // Fetch origin/main to ensure we have the latest
    await exec('git', ['fetch', 'origin', 'main'], { cwd: repoPath })
    // Create worktree detached at origin/main
    await exec('git', ['worktree', 'add', '--detach', scratchDir, 'origin/main'], { cwd: repoPath })

    // Read current VERSION
    const versionFile = path.join(scratchDir, 'VERSION')
    let currentVersion = '0.0.0'
    if (existsSync(versionFile)) {
      currentVersion = readFileSync(versionFile, 'utf-8').trim()
    }

    // Compute new version
    const type = bumpType(labels)
    const newVersion = bumpVersion(currentVersion, type)

    // Write VERSION
    writeFileSync(versionFile, newVersion + '\n')

    // Prepend to CHANGELOG.md
    const changelogFile = path.join(scratchDir, 'CHANGELOG.md')
    let changelogContent = ''
    if (existsSync(changelogFile)) {
      changelogContent = readFileSync(changelogFile, 'utf-8')
    }

    const dateStr = new Date().toISOString().split('T')[0]
    const entry = `## ${newVersion} - ${dateStr}\n\n${formatChangelogEntry(newVersion, ticketTitle, prUrl, dateStr)}\n`
    const heading = '# Changelog\n\n'

    if (!changelogContent.includes('# Changelog')) {
      changelogContent = heading + entry + changelogContent
    } else {
      changelogContent = changelogContent.replace('# Changelog\n\n', `# Changelog\n\n${entry}`)
    }

    writeFileSync(changelogFile, changelogContent)

    // Commit and push
    await exec('git', ['add', 'VERSION', 'CHANGELOG.md'], { cwd: scratchDir })
    await exec('git', ['commit', '-m', `release: v${newVersion}`], { cwd: scratchDir })

    // Push with retry logic (reuse the withRetry pattern from failure.js if available,
    // but for now do a simple push)
    await exec('git', ['push', 'origin', `HEAD:main`], { cwd: scratchDir })
  } finally {
    // Clean up worktree
    try {
      await exec('git', ['worktree', 'remove', '--force', scratchDir], { cwd: repoPath })
    } catch {
      // If worktree removal fails, try to remove the directory directly
    }
    try {
      await rm(scratchDir, { recursive: true, force: true })
    } catch {
      // Ignore cleanup errors
    }
  }
}
