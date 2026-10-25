import { existsSync } from 'fs'
import { listRepoDocTree, fetchFileContent, searchableText } from './docs.js'
import { listLocalTree, readLocalFile, localFileStates } from './docs_local.js'
import { groupDocSections, isDocMarkdown } from './doc_paths.js'
import { docsForRepo } from './docs_search.js'

// Everything the Docs tab asks for, driven by the project catalog
// (lib/project_catalog.py) instead of "GitHub repos with a CONTEXT.md": every
// project gets a card; its docs come from a local clone when one exists, else
// GitHub. The master "Where things are" doc is a pseudo-project at the top.
export const MASTER_ID = '__master__'
const CARD = { path: 'PROJECT.md', label: 'Project card' }
const MASTER_FILE = { path: 'WHERE-THINGS-ARE.md', label: 'Where things are' }

export const ghName = (rec) => rec.repo.split('/')[1]

// Build a tree from cached docs for a specific repo, reusing groupDocSections and isDocMarkdown
export function treeFromDocs(docs, repoId) {
  const repoDocs = docs.filter((d) => d.repo === repoId)
  const tree = []

  // Add CONTEXT.md and README.md first
  const contextDoc = repoDocs.find((d) => d.path === 'CONTEXT.md')
  if (contextDoc) tree.push({ path: 'CONTEXT.md', label: 'CONTEXT.md' })

  const readmeDoc = repoDocs.find((d) => d.path === 'README.md')
  if (readmeDoc) tree.push({ path: 'README.md', label: 'README.md' })

  // Group docs/ sections using the same logic as listRepoDocTree
  const docPaths = repoDocs
    .filter((d) => isDocMarkdown(d.path))
    .map((d) => d.path)
  const docSections = groupDocSections(docPaths)
  tree.push(...docSections)

  // Root-level notebooks (trailing section)
  const notebookPaths = repoDocs
    .filter((d) => !d.path.includes('/') && d.path.endsWith('.ipynb'))
    .map((d) => d.path)
    .sort((a, b) => a.localeCompare(b))
  if (notebookPaths.length > 0) {
    tree.push({
      section: 'notebooks',
      items: notebookPaths.map((p) => ({ path: p, label: p }))
    })
  }

  return tree
}

export function createDocsService({ getCatalog, exec, readMaster, fallbackRepos = () => [], getIndexer, onRepoOpened }) {
  const catalog = () => getCatalog()
  const dirOf = (rec) => (rec?.localPaths || []).find((p) => existsSync(p)) || null

  // Default indexer: empty load, no persistence. Can be overridden via getIndexer injection.
  const createDefaultIndexer = () => ({ peek: () => null, applyRepoDocs: () => {}, upsertDoc: () => {} })
  const indexer = getIndexer ? getIndexer : createDefaultIndexer

  function find(id) {
    const cat = catalog()
    if (cat) return cat.projects.find((p) => p.id === id) || null
    // No catalog yet: treat the id as a GitHub repo name from the old doc-first list.
    return fallbackRepos().some((r) => r.name === id)
      ? { id, name: id, kind: 'repo', repo: `G-Eskayo/${id}`, localPaths: [], docs: { context: true, readme: true, adrCount: 0 }, summary_md: `# ${id}\n` }
      : null
  }

  async function repos() {
    const cat = catalog()
    const master = { id: MASTER_ID, name: 'Where things are', kind: 'master', status: 'active', local: null }
    if (!cat) {
      return { generated_at: null, repos: [master, ...fallbackRepos().map((r) => ({ id: r.name, name: r.name, kind: 'repo', status: 'active', local: null }))] }
    }
    return {
      generated_at: cat.generated_at,
      repos: [
        master,
        ...cat.projects.map((p) => ({ id: p.id, name: p.name, kind: p.kind, status: p.status, local: dirOf(p), tags: p.tags, repo: p.repo, board: p.board }))
      ]
    }
  }

  // Per-repo single-flight cache for GitHub tree fetches
  const treeInflight = new Map()

  async function tree(id) {
    if (id === MASTER_ID) return { source: 'master', dir: null, tree: [MASTER_FILE] }
    const rec = find(id)
    if (!rec) throw new Error(`Unknown project: ${id}`)
    const dir = dirOf(rec)
    if (dir) {
      const states = await localFileStates(dir)
      const annotate = (e) => ({ ...e, state: states[e.path] || null })
      const local = listLocalTree(dir).map((e) => (e.section ? { ...e, items: e.items.map(annotate) } : annotate(e)))
      return { source: 'local', dir, tree: [CARD, ...local] }
    }
    if (rec.repo && rec.docs.context) {
      // Call onRepoOpened hook unconditionally once per call, before cache check (cache hit or miss)
      if (onRepoOpened) {
        Promise.resolve(onRepoOpened(rec)).catch(() => {})
      }
      // Check indexer cache first
      const idx = indexer().peek()
      if (idx?.docs && docsForRepo(idx, id).length > 0) {
        const cached = treeFromDocs(idx.docs, id)
        return { source: 'github', dir: null, tree: [CARD, ...cached], fetchedAt: idx.repos?.[id]?.fetchedAt }
      }
      // Single-flight fetch on cache miss
      if (!treeInflight.has(id)) {
        treeInflight.set(
          id,
          listRepoDocTree(exec, ghName(rec))
            .then((t) => {
              treeInflight.delete(id)
              return { source: 'github', dir: null, tree: [CARD, ...t], fetchedAt: new Date().toISOString() }
            })
            .catch((e) => {
              treeInflight.delete(id)
              throw e
            })
        )
      }
      try {
        return await treeInflight.get(id)
      } catch {
        // fall through to what the catalog already knows
      }
    }
    const known = rec.repo && rec.docs.readme ? [{ path: 'README.md', label: 'README.md' }] : []
    return { source: rec.repo && known.length ? 'github' : 'card', dir: null, tree: [CARD, ...known] }
  }

  // Per-file single-flight cache for GitHub content fetches
  const contentInflight = new Map()

  async function content(id, filePath) {
    if (id === MASTER_ID) {
      const text = readMaster()
      if (text == null) throw new Error('The master doc has not been generated yet')
      return text
    }
    const rec = find(id)
    if (!rec) throw new Error(`Unknown project: ${id}`)
    if (filePath === CARD.path) return rec.summary_md
    const dir = dirOf(rec)
    if (dir) return readLocalFile(dir, filePath)
    if (!rec.repo) throw new Error(`${rec.name} has no readable copy of ${filePath}`)

    // Check indexer cache first
    const idx = indexer().peek()
    if (idx?.docs) {
      const cached = idx.docs.find((d) => d.repo === id && d.path === filePath)
      if (cached) return cached.raw ?? cached.content
    }

    // Fetch from GitHub and upsert into index with per-file single-flight cache
    const key = `${id}:${filePath}`
    if (!contentInflight.has(key)) {
      contentInflight.set(
        key,
        fetchFileContent(exec, ghName(rec), filePath)
          .then((text) => {
            contentInflight.delete(key)
            const searchable = searchableText(filePath, text)
            const doc = { repo: id, path: filePath, label: filePath, content: searchable }
            if (searchable !== text) doc.raw = text
            indexer().upsertDoc(doc)
            return text
          })
          .catch((e) => {
            contentInflight.delete(key)
            throw e
          })
      )
    }
    return contentInflight.get(key)
  }

  // Docs read live from disk (so uncommitted edits are searchable), plus every card and the master.
  async function localDocs() {
    const cat = catalog()
    const reposWithLocal = new Set()
    const docs = []
    const master = readMaster()
    if (master != null) docs.push({ repo: MASTER_ID, path: MASTER_FILE.path, label: MASTER_FILE.label, content: master })
    for (const rec of cat?.projects || []) {
      docs.push({ repo: rec.id, path: CARD.path, label: CARD.label, content: rec.summary_md })
      const dir = dirOf(rec)
      if (!dir) continue
      reposWithLocal.add(rec.id)
      const states = await localFileStates(dir)
      for (const f of listLocalTree(dir).flatMap((e) => (e.section ? e.items : [e]))) {
        try {
          docs.push({ repo: rec.id, path: f.path, label: f.label, content: searchableText(f.path, readLocalFile(dir, f.path)), state: states[f.path] || null })
        } catch {
          // unreadable file: the rest still searches
        }
      }
    }
    return { repos: reposWithLocal, docs }
  }

  function githubIndexRepos() {
    const cat = catalog()
    if (!cat) return fallbackRepos().map((r) => ({ name: r.name, id: r.name }))
    return cat.projects.filter((p) => p.repo && !dirOf(p) && (p.docs.context || p.docs.readme)).map((p) => ({ name: ghName(p), id: p.id }))
  }

  const localDirs = () => (catalog()?.projects || []).map(dirOf).filter(Boolean)

  return { repos, tree, content, localDocs, githubIndexRepos, localDirs }
}
