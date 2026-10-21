import { existsSync } from 'fs'
import { listRepoDocTree, fetchFileContent, searchableText } from './docs.js'
import { listLocalTree, readLocalFile, localFileStates } from './docs_local.js'
import { UNSORTED_ID } from './deliverables.js'
import { extractOutline } from '../../src/lib/docs_text.js'

// Everything the Docs tab asks for, driven by the project catalog
// (lib/project_catalog.py) instead of "GitHub repos with a CONTEXT.md": every
// project gets a card; its docs come from a local clone when one exists, else
// GitHub. The master "Where things are" doc is a pseudo-project at the top.
export const MASTER_ID = '__master__'
const CARD = { path: 'PROJECT.md', label: 'Project card' }
const MASTER_FILE = { path: 'WHERE-THINGS-ARE.md', label: 'Where things are' }
const copyAge = (copy) => ({ savedAt: copy?.savedAt ?? null, checkedAt: copy?.checkedAt ?? null })

// `saved` (docs_saved.js, #565) holds the saved copy of GitHub-only projects: with it, tree and content never call
// GitHub, and revalidate (sent once when a project is opened) is the only request.
// `deliverables` (deliverables.js, #570) is the outbox match map: each project's tree also carries the outbox items
// matched to it, and "Unsorted deliverables" lists what no project claims. Everything it returns is local or saved.
export { UNSORTED_ID }
// `onStatesChanged(id)`: the uncommitted/unpushed badges (local `git status`, 75-100 ms) are read after the tree is
// drawn, from the last-known states; when they differ, this is called so the open view redraws them in place.
export function createDocsService({ getCatalog, exec, readMaster, fallbackRepos = () => [], saved = null, deliverables = null, onStatesChanged = () => {} }) {
  const lastStates = new Map() // dir -> { path: state }
  const statesInflight = new Map()
  function refreshStates(id, dir) {
    if (statesInflight.has(dir)) return statesInflight.get(dir)
    const p = localFileStates(dir)
      .then((states) => {
        const before = JSON.stringify(lastStates.get(dir) ?? null)
        lastStates.set(dir, states)
        if (before !== JSON.stringify(states)) onStatesChanged(id)
        return states
      })
      .catch(() => lastStates.get(dir) || {})
      .finally(() => statesInflight.delete(dir))
    statesInflight.set(dir, p)
    return p
  }
  const outbox = () => deliverables?.view() || { byProject: {}, unsorted: { whole: [], leftovers: [] }, count: 0 }
  const unsortedEntry = () => (deliverables ? [{ id: UNSORTED_ID, name: 'Unsorted deliverables', kind: 'unsorted', status: 'active', local: null, count: outbox().count }] : [])
  const catalog = () => getCatalog()
  const dirOf = (rec) => (rec?.localPaths || []).find((p) => existsSync(p)) || null

  function find(id) {
    const cat = catalog()
    if (cat) return cat.projects.find((p) => p.id === id) || null
    // No catalog yet: treat the id as a GitHub repo name from the old doc-first list.
    return fallbackRepos().some((r) => r.name === id)
      ? { id, name: id, kind: 'repo', repo: `G-Eskayo/${id}`, localPaths: [], docs: { context: true, readme: true, adrCount: 0 }, summary_md: `# ${id}\n` }
      : null
  }
  const ghName = (rec) => rec.repo.split('/')[1]

  async function repos() {
    const cat = catalog()
    const master = { id: MASTER_ID, name: 'Where things are', kind: 'master', status: 'active', local: null }
    if (!cat) {
      return { generated_at: null, repos: [master, ...unsortedEntry(), ...fallbackRepos().map((r) => ({ id: r.name, name: r.name, kind: 'repo', status: 'active', local: null }))] }
    }
    return {
      generated_at: cat.generated_at,
      repos: [
        master,
        ...unsortedEntry(),
        ...cat.projects.map((p) => ({ id: p.id, name: p.name, kind: p.kind, status: p.status, local: dirOf(p), tags: p.tags, repo: p.repo, board: p.board }))
      ]
    }
  }

  async function tree(id) {
    if (id === UNSORTED_ID) {
      const u = outbox().unsorted
      return { source: 'unsorted', dir: null, tree: [], deliverables: u.whole, leftovers: u.leftovers }
    }
    const t = await docTree(id)
    return id === MASTER_ID ? t : { ...t, deliverables: outbox().byProject[id] || [] }
  }

  async function docTree(id) {
    if (id === MASTER_ID) return { source: 'master', dir: null, tree: [MASTER_FILE] }
    const rec = find(id)
    if (!rec) throw new Error(`Unknown project: ${id}`)
    const dir = dirOf(rec)
    if (dir) {
      // Saved state first: the last-known badges now (none on the first open), the fresh ones in the background.
      const states = lastStates.get(dir) || {}
      refreshStates(id, dir)
      const annotate = (e) => ({ ...e, state: states[e.path] || null })
      const local = listLocalTree(dir).map((e) => (e.section ? { ...e, items: e.items.map(annotate) } : annotate(e)))
      return { source: 'local', dir, tree: [CARD, ...local] }
    }
    if (saved && rec.repo) {
      const copy = saved.peek(rec.repo)
      if (copy?.tree?.length) return { source: 'github', dir: null, tree: [CARD, ...copy.tree], copy: copyAge(copy) }
      // No copy yet: what the catalog knows, at once; revalidate fills the copy and the view updates in place.
      const known = [...(rec.docs.context ? [{ path: 'CONTEXT.md', label: 'CONTEXT.md' }] : []), ...(rec.docs.readme ? [{ path: 'README.md', label: 'README.md' }] : [])]
      return { source: known.length ? 'github' : 'card', dir: null, tree: [CARD, ...known], copy: { savedAt: null, checkedAt: null } }
    }
    if (rec.repo && rec.docs.context) {
      try {
        return { source: 'github', dir: null, tree: [CARD, ...(await listRepoDocTree(exec, ghName(rec)))] }
      } catch {
        // fall through to what the catalog already knows
      }
    }
    const known = rec.repo && rec.docs.readme ? [{ path: 'README.md', label: 'README.md' }] : []
    return { source: rec.repo && known.length ? 'github' : 'card', dir: null, tree: [CARD, ...known] }
  }

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
    if (saved) return saved.content(rec.repo, filePath)
    return fetchFileContent(exec, ghName(rec), filePath)
  }

  // The first heading of each doc, for the project overview's summary cards. Reads local files or the saved copy only.
  async function headings(id, paths) {
    const out = {}
    for (const p of (Array.isArray(paths) ? paths : []).slice(0, 12)) {
      try {
        const text = await content(id, String(p))
        out[p] = extractOutline(p.endsWith('.ipynb') ? '' : text)[0]?.text || null
      } catch {
        out[p] = null
      }
    }
    return out
  }

  // Sent once when a GitHub-only project is opened: one conditional request (a 304 is free). On a change the saved
  // copy is refreshed and the new tree comes back, so the open view can update in place.
  async function revalidate(id) {
    const rec = id === MASTER_ID ? null : find(id)
    if (!saved || !rec?.repo || dirOf(rec) || !(rec.docs.context || rec.docs.readme)) return { status: 'not-github' }
    const r = await saved.revalidate(rec.repo)
    const copy = saved.peek(rec.repo)
    return { ...r, tree: copy?.tree?.length ? [CARD, ...copy.tree] : undefined, copy: copyAge(copy) }
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
    // Deliverables (#570): one search covers docs and deliverables. Cached per outbox item in deliverables.js.
    if (deliverables) docs.push(...deliverables.searchDocs())
    return { repos: reposWithLocal, docs }
  }

  function githubIndexRepos() {
    const cat = catalog()
    if (!cat) return fallbackRepos().map((r) => ({ name: r.name, id: r.name }))
    return cat.projects.filter((p) => p.repo && !dirOf(p) && (p.docs.context || p.docs.readme)).map((p) => ({ name: ghName(p), id: p.id, repo: p.repo }))
  }

  const localDirs = () => (catalog()?.projects || []).map(dirOf).filter(Boolean)

  return { repos, tree, content, headings, revalidate, localDocs, githubIndexRepos, localDirs }
}
