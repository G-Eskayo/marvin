import { readFileSync, existsSync, readdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { execFile } from 'child_process'
import { promisify } from 'util'
import { groupDocSections, isDocMarkdown } from './doc_paths.js'

// Local-first reading for the Docs tab. The tab used to read only GitHub's
// default branch, so uncommitted or unpushed doc edits were invisible. For any
// repo with a clone on this machine we read the working tree instead and say
// which files differ from GitHub; repos with no clone here fall back to GitHub.
const execFileP = promisify(execFile)
const GH_OWNER = 'G-Eskayo'
const DOC_PATHS = ['CONTEXT.md', 'README.md', 'docs', ':(glob)*.ipynb']

async function git(dir, args) {
  const { stdout } = await execFileP('git', ['-C', dir, ...args], { maxBuffer: 10 * 1024 * 1024 })
  return stdout
}

export function defaultCandidateDirs() {
  const dirs = [path.join(homedir(), '.agents')]
  for (const parent of [path.join(homedir(), 'Documents', 'Projects'), path.join(homedir(), 'Developer')]) {
    try {
      for (const name of readdirSync(parent)) dirs.push(path.join(parent, name))
    } catch {
      // parent doesn't exist on this machine
    }
  }
  return dirs
}

// The working copy that is actually moving wins when several clones exist
// (found 2026-10-05: clarity-captions is cloned in two places, one 2 days stale).
export async function resolveLocalClone(repoName, { candidateDirs = defaultCandidateDirs() } = {}) {
  const originRe = new RegExp(`[:/]${GH_OWNER}/${repoName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(\\.git)?$`)
  let best = null
  for (const dir of candidateDirs) {
    if (!existsSync(path.join(dir, '.git'))) continue
    try {
      const origin = (await git(dir, ['remote', 'get-url', 'origin'])).trim()
      if (!originRe.test(origin)) continue
      const head = Number((await git(dir, ['log', '-1', '--format=%ct'])).trim()) || 0
      if (!best || head > best.head) best = { dir, head }
    } catch {
      // not a usable git checkout
    }
  }
  return best ? best.dir : null
}

// Same shape as docs.js's listRepoDocTree so the UI treats both sources alike.
// Every file under docs/, as repo-relative paths. Hidden folders and node_modules are skipped; depth is bounded so a
// stray symlink loop or a vendored tree cannot stall the tab.
function walkDocs(dir, rel = 'docs', depth = 0, out = []) {
  if (depth > 6) return out
  let entries
  try {
    entries = readdirSync(path.join(dir, rel), { withFileTypes: true })
  } catch {
    return out   // no docs/ yet
  }
  for (const e of entries) {
    if (e.name.startsWith('.') || e.name === 'node_modules') continue
    if (e.isDirectory()) walkDocs(dir, `${rel}/${e.name}`, depth + 1, out)
    else if (e.isFile()) out.push(`${rel}/${e.name}`)
  }
  return out
}

export function listLocalTree(dir) {
  const tree = existsSync(path.join(dir, 'CONTEXT.md')) ? [{ path: 'CONTEXT.md', label: 'CONTEXT.md' }] : []
  if (existsSync(path.join(dir, 'README.md'))) tree.push({ path: 'README.md', label: 'README.md' })
  tree.push(...groupDocSections(walkDocs(dir)))
  try {
    const books = readdirSync(dir)
      .filter((n) => n.endsWith('.ipynb'))
      .sort((a, b) => a.localeCompare(b))
      .map((n) => ({ path: n, label: n }))
    if (books.length) tree.push({ section: 'notebooks', items: books })
  } catch {
    // unreadable directory
  }
  return tree
}

const ALLOWED_ROOT = /^(CONTEXT\.md|README\.md|[^/]+\.ipynb)$/

export function readLocalFile(dir, filePath) {
  const normalized = path.posix.normalize(String(filePath))
  if (normalized.split('/').includes('..') || !(ALLOWED_ROOT.test(normalized) || isDocMarkdown(normalized))) {
    throw new Error(`Not a readable doc path: ${filePath}`)
  }
  return readFileSync(path.join(dir, normalized), 'utf-8')
}

// path -> 'uncommitted' | 'unpushed' (absent = identical to origin/main as last fetched).
export async function localFileStates(dir) {
  const states = {}
  try {
    const out = await git(dir, ['status', '--porcelain', '--untracked-files=all', '--', ...DOC_PATHS])
    for (const line of out.split('\n')) {
      if (line.length > 3) states[line.slice(3).replace(/^"|"$/g, '')] = 'uncommitted'
    }
  } catch {
    // leave unknown rather than guess
  }
  try {
    const out = await git(dir, ['diff', '--name-only', 'origin/main', '--', ...DOC_PATHS])
    for (const p of out.split('\n').filter(Boolean)) states[p] ??= 'unpushed'
  } catch {
    // no origin/main ref locally
  }
  return states
}
