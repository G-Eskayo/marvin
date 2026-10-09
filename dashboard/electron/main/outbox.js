import { readFileSync, readdirSync, lstatSync, existsSync, realpathSync } from 'fs'
import { homedir } from 'os'
import path from 'path'

const OUTBOX_ROOT = path.join(homedir(), '.claude', 'outbox')
const MAX_FILE_SIZE = 2 * 1024 * 1024 // 2 MB
const MAX_DEPTH = 8

function resolveOutboxPath(relPath) {
  // Reject non-string or absolute input
  if (typeof relPath !== 'string') {
    throw new Error('Path must be a string')
  }
  if (path.isAbsolute(relPath)) {
    throw new Error('Absolute paths not allowed')
  }

  // Normalize and reject any .. segments
  const normalized = path.posix.normalize(relPath)
  if (normalized.split('/').includes('..')) {
    throw new Error('Traversal (..) not allowed')
  }

  // Join to root and resolve both paths to their real locations
  const fullPath = path.join(OUTBOX_ROOT, normalized)
  let realFull, realRoot
  try {
    realFull = realpathSync(fullPath)
    realRoot = realpathSync(OUTBOX_ROOT)
  } catch {
    // If realpath fails, the file likely doesn't exist, but we can still validate the intent
    // For validation, just ensure the normalized path doesn't escape
    if (!fullPath.startsWith(OUTBOX_ROOT + path.sep)) {
      throw new Error('Path escapes outbox root')
    }
    return fullPath
  }

  // Ensure resolved path stays inside outbox root
  if (!realFull.startsWith(realRoot + path.sep) && realFull !== realRoot) {
    throw new Error('Path escapes outbox root')
  }

  return fullPath
}

export function listOutboxTree(relPath = '', depth = 0) {
  const currentPath = relPath ? path.join(OUTBOX_ROOT, relPath) : OUTBOX_ROOT
  if (depth > MAX_DEPTH) return []

  if (!existsSync(currentPath)) {
    return []
  }

  let entries
  try {
    entries = readdirSync(currentPath, { withFileTypes: true })
  } catch {
    return []
  }

  const items = []

  // Separate directories and files
  const dirs = []
  const files = []

  for (const entry of entries) {
    const entryPath = relPath ? `${relPath}/${entry.name}` : entry.name
    if (entry.isDirectory()) {
      dirs.push({ path: entryPath, name: entry.name })
    } else if (entry.isFile()) {
      files.push({ path: entryPath, name: entry.name })
    }
  }

  // Sort each group alphabetically
  dirs.sort((a, b) => a.name.localeCompare(b.name))
  files.sort((a, b) => a.name.localeCompare(b.name))

  // Add directories first with their recursive children
  for (const dir of dirs) {
    const children = listOutboxTree(dir.path, depth + 1)
    items.push({
      path: dir.path,
      type: 'dir',
      children
    })
  }

  // Add files
  for (const file of files) {
    items.push({
      path: file.path,
      type: 'file'
    })
  }

  return items
}

export function readOutboxFile(relPath) {
  const fullPath = resolveOutboxPath(relPath)

  // Check it's a regular file
  let stat
  try {
    stat = lstatSync(fullPath)
  } catch {
    throw new Error(`File not found: ${relPath}`)
  }

  if (!stat.isFile()) {
    throw new Error(`Not a regular file: ${relPath}`)
  }

  // Size check
  if (stat.size > MAX_FILE_SIZE) {
    const content = readFileSync(fullPath, 'utf-8').slice(0, MAX_FILE_SIZE)
    return {
      content,
      kind: detectKind(relPath, content),
      truncated: true
    }
  }

  const content = readFileSync(fullPath, 'utf-8')
  return {
    content,
    kind: detectKind(relPath, content),
    truncated: false
  }
}

function detectKind(filePath, content) {
  const ext = path.extname(filePath).toLowerCase().slice(1)

  if (ext === 'md') return 'markdown'
  if (ext === 'json') {
    // Verify it's valid JSON before claiming it's json kind
    try {
      JSON.parse(content)
      return 'json'
    } catch {
      // Invalid JSON, fall back to text
      return 'text'
    }
  }

  return 'text'
}
