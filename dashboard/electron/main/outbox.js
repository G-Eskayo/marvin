import { lstatSync, readFileSync, readdirSync, existsSync } from 'fs'
import { join, resolve } from 'path'
import { homedir } from 'os'

export const OUTBOX_DIR = join(homedir(), '.claude', 'outbox')

// Reject absolute paths and ensure the resolved realpath is within outboxDir.
// This is the security boundary -- everything else calls through this guard.
export function resolveWithinOutbox(relativePath, outboxDir = OUTBOX_DIR) {
  if (!relativePath) throw new Error('Empty path')
  if (relativePath.startsWith('/')) throw new Error('Absolute paths not allowed')

  const candidate = resolve(outboxDir, relativePath)
  const canonical = resolve(candidate)

  // Path traversal check: canonical must be outboxDir or a descendant.
  // Use path.sep-bounded prefix to avoid "outboxDir-prefix" collisions.
  if (canonical !== outboxDir && !canonical.startsWith(outboxDir + require('path').sep)) {
    throw new Error('Path traversal attempt')
  }

  return canonical
}

// Recursive tree walk, skipping symlinks entirely, sorted dirs-then-files.
export function listTree(outboxDir = OUTBOX_DIR) {
  if (!existsSync(outboxDir)) return []

  try {
    const entries = readdirSync(outboxDir, { withFileTypes: true }).sort((a, b) => {
      const aIsDir = a.isDirectory()
      const bIsDir = b.isDirectory()
      if (aIsDir !== bIsDir) return aIsDir ? -1 : 1
      return a.name.localeCompare(b.name)
    })

    return entries
      .filter((e) => !e.isSymbolicLink())
      .map((e) => {
        const name = e.name
        const relPath = name
        const type = e.isDirectory() ? 'dir' : 'file'

        let result = { name, relPath, type }
        if (type === 'dir') {
          result.children = walkDir(join(outboxDir, relPath), outboxDir)
        }
        return result
      })
  } catch {
    return []
  }
}

function walkDir(fullPath, outboxDir) {
  try {
    const entries = readdirSync(fullPath, { withFileTypes: true }).sort((a, b) => {
      const aIsDir = a.isDirectory()
      const bIsDir = b.isDirectory()
      if (aIsDir !== bIsDir) return aIsDir ? -1 : 1
      return a.name.localeCompare(b.name)
    })

    return entries
      .filter((e) => !e.isSymbolicLink())
      .map((e) => {
        const name = e.name
        const relPath = join(fullPath, name).replace(outboxDir + require('path').sep, '')
        const type = e.isDirectory() ? 'dir' : 'file'

        let result = { name, relPath, type }
        if (type === 'dir') {
          result.children = walkDir(join(fullPath, name), outboxDir)
        }
        return result
      })
  } catch {
    return []
  }
}

// Read a file with size cap and content-type classification.
export function readOutboxFile(relativePath, outboxDir = OUTBOX_DIR) {
  const resolved = resolveWithinOutbox(relativePath, outboxDir)

  const stat = lstatSync(resolved)
  if (!stat.isFile()) throw new Error('Not a file')

  const MAX_SIZE = 2 * 1024 * 1024 // 2 MB
  if (stat.size > MAX_SIZE) {
    return { kind: 'text', content: '', truncated: true }
  }

  const content = readFileSync(resolved, 'utf-8')

  // Classify by extension
  if (relativePath.endsWith('.md') || relativePath.endsWith('.markdown')) {
    return { kind: 'markdown', content, truncated: false }
  }

  if (relativePath.endsWith('.json')) {
    try {
      const parsed = JSON.parse(content)
      return { kind: 'json', content: JSON.stringify(parsed, null, 2), truncated: false }
    } catch {
      // Corrupt JSON falls back to text
      return { kind: 'text', content, truncated: false }
    }
  }

  return { kind: 'text', content, truncated: false }
}
