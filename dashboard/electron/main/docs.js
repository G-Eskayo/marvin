import { notebookToMarkdown } from '../../src/lib/ipynb.js'
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { groupDocSections } from './doc_paths.js'

// Cross-project documentation browser. Deliberately GitHub-API-backed, not
// local-filesystem-backed, unlike dispatch_status.js/health.js -- these are
// git-repo-canonical docs (CONTEXT.md, docs/adr/*.md), not local-only state
// like the outbox (#89) or a dispatch lock. Reading via `gh api` means this
// runs identically on both machines without needing a matching local clone
// of every project to exist on whichever machine the dashboard happens to
// be running on -- same "runs identically on both machines" bar #89's own
// acceptance criteria already set, just met a different way since the
// underlying data isn't local-only here.
const GH_OWNER = 'G-Eskayo'
const CACHE_PATH = path.join(homedir(), '.claude', 'logs', 'doc-repos-cache.json')

function run(execFileAsync, args) {
  return execFileAsync('gh', args, { maxBuffer: 10 * 1024 * 1024 })
}

async function fileExists(execFileAsync, repo, filePath) {
  try {
    await run(execFileAsync, ['api', `repos/${GH_OWNER}/${repo}/contents/${filePath}`, '--jq', '.name'])
    return true
  } catch {
    return false
  }
}

// Auto-discovered, not hand-maintained -- same coverage philosophy as the
// Health tab (ADR 0033): a repo qualifies by actually having CONTEXT.md,
// not by being added to a list someone has to remember to update.
export async function discoverDocFirstRepos(execFileAsync, cachePath = CACHE_PATH) {
  const { stdout } = await run(execFileAsync, [
    'repo', 'list', GH_OWNER, '--limit', '200',
    '--json', 'name,description,pushedAt,isArchived'
  ])
  const repos = JSON.parse(stdout).filter((r) => !r.isArchived)
  const checked = await Promise.all(
    repos.map(async (r) => ({ ...r, hasContext: await fileExists(execFileAsync, r.name, 'CONTEXT.md') }))
  )
  const qualified = checked.filter((r) => r.hasContext).map(({ hasContext, ...r }) => r)
  mkdirSync(path.dirname(cachePath), { recursive: true })
  writeFileSync(cachePath, JSON.stringify({ generated_at: new Date().toISOString(), repos: qualified }, null, 2))
  return qualified
}

export function readCachedRepos(cachePath = CACHE_PATH) {
  if (!existsSync(cachePath)) return { generated_at: null, repos: [] }
  try {
    return JSON.parse(readFileSync(cachePath, 'utf-8'))
  } catch {
    return { generated_at: null, repos: [] }
  }
}

// docs/adr/ is optional (a brand-new repo may only have CONTEXT.md yet) --
// listing it 404ing just means an empty adr section, not an error.
export async function listRepoDocTree(execFileAsync, repo) {
  const tree = [{ path: 'CONTEXT.md', label: 'CONTEXT.md' }]
  if (await fileExists(execFileAsync, repo, 'README.md')) {
    tree.push({ path: 'README.md', label: 'README.md' })
  }
  // One recursive tree call gives every doc under docs/ and the root notebooks; if it fails, fall back to listing
  // docs/adr/ and the root directly, as before.
  try {
    const { stdout } = await run(execFileAsync, ['api', `repos/${GH_OWNER}/${repo}/git/trees/HEAD?recursive=1`])
    const paths = (JSON.parse(stdout).tree || []).filter((e) => e.type === 'blob').map((e) => e.path)
    tree.push(...groupDocSections(paths))
    const books = paths.filter((p) => !p.includes('/') && p.endsWith('.ipynb')).sort((a, b) => a.localeCompare(b)).map((p) => ({ path: p, label: p }))
    if (books.length) tree.push({ section: 'notebooks', items: books })
    return tree
  } catch {
    // fall through to the two direct listings
  }
  try {
    const { stdout } = await run(execFileAsync, ['api', `repos/${GH_OWNER}/${repo}/contents/docs/adr`])
    const entries = JSON.parse(stdout)
    const adrs = entries
      .filter((e) => e.type === 'file' && e.name.endsWith('.md'))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((e) => ({ path: `docs/adr/${e.name}`, label: e.name }))
    if (adrs.length) tree.push({ section: 'docs/adr/', items: adrs })
  } catch {
    // no docs/adr/ yet -- fine, not every repo has ADRs
  }
  try {
    const { stdout } = await run(execFileAsync, ['api', `repos/${GH_OWNER}/${repo}/contents`])
    const books = JSON.parse(stdout)
      .filter((e) => e.type === 'file' && e.name.endsWith('.ipynb'))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((e) => ({ path: e.name, label: e.name }))
    if (books.length) tree.push({ section: 'notebooks', items: books })
  } catch {
    // listing the root failed: the notebooks section is optional
  }
  return tree
}

// What the text search should see: a notebook is searched as the markdown a reader sees (minus the inline images),
// never as its raw JSON.
export function searchableText(filePath, content) {
  return filePath.endsWith('.ipynb') ? notebookToMarkdown(content, { images: false }) : content
}

export async function fetchFileContent(execFileAsync, repo, filePath) {
  if (filePath.endsWith('.ipynb')) {
    // Notebooks carry their images inline and easily pass the contents API's 1 MB base64 limit: ask for the raw bytes.
    const { stdout } = await execFileAsync(
      'gh', ['api', '-H', 'Accept: application/vnd.github.raw', `repos/${GH_OWNER}/${repo}/contents/${filePath}`],
      { maxBuffer: 100 * 1024 * 1024 }
    )
    return stdout
  }
  const { stdout } = await run(execFileAsync, [
    'api', `repos/${GH_OWNER}/${repo}/contents/${filePath}`, '--jq', '.content'
  ])
  return Buffer.from(stdout.trim(), 'base64').toString('utf-8')
}
