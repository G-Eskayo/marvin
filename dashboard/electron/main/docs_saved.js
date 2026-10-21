import { createHash } from 'crypto'
import { readFileSync, writeFileSync, mkdirSync, renameSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { groupDocSections } from './doc_paths.js'
import { fetchFileContent } from './docs.js'

// The saved copy of a GitHub-only project's docs (#565 "Docs tab: stop calling GitHub on every click for projects
// without a local clone"). Before this, opening such a project cost 2-4 `gh api` calls and every file open one more,
// every time. Now:
//
// - Clicks read the saved copy only (memory, else one JSON file per repo): zero network calls.
// - Opening the project sends ONE conditional request for its git tree (If-None-Match with the saved ETag, the same
//   pattern as webhook-server/gh_watch.js). A 304 is free against the rate limit and ends there. A 200 gives the new
//   tree with every file's blob sha, so only docs whose sha changed are downloaded (O(changed files)).
// - The first copy is seeded from the docs search index, which already holds every GitHub doc's text
//   (docs_search.js); git blob shas tell which seeded texts are still current, so the first check downloads only the
//   ones that differ.
//
// Space: O(docs text) of the GitHub-only repos, one file each. Time per click: O(1) map lookups.
export const SAVED_DIR = path.join(homedir(), '.claude', 'logs', 'docs-github')
const VERSION = 1

// git's blob id: sha1 of "blob <byte length>\0<bytes>". Lets a seeded copy be checked against the tree without a download.
export function gitBlobSha(text) {
  const body = Buffer.from(String(text), 'utf8')
  return createHash('sha1').update(`blob ${body.length}\0`).update(body).digest('hex')
}

// The Docs tab's tree for a repo, from its file paths: CONTEXT.md, README.md, every .md under docs/ by folder, root
// notebooks. The same listing docs_local.js gives a local clone.
export function docTreeFromPaths(paths) {
  const set = new Set(paths)
  const tree = []
  if (set.has('CONTEXT.md')) tree.push({ path: 'CONTEXT.md', label: 'CONTEXT.md' })
  if (set.has('README.md')) tree.push({ path: 'README.md', label: 'README.md' })
  tree.push(...groupDocSections(paths))
  const books = [...set].filter((p) => !p.includes('/') && p.endsWith('.ipynb')).sort((a, b) => a.localeCompare(b)).map((p) => ({ path: p, label: p }))
  if (books.length) tree.push({ section: 'notebooks', items: books })
  return tree
}

const flatPaths = (tree) => tree.flatMap((e) => (e.section ? e.items : [e])).map((e) => e.path)
const isDocPath = (p) => typeof p === 'string' && flatPaths(docTreeFromPaths([p])).includes(p)

// One file per repo, named from a slug of "owner/name": a hostile name can never point outside the folder.
export function savedFileFor(dir, repo) {
  const slug = String(repo).toLowerCase().replace(/[^a-z0-9._-]+/g, '_').replace(/^\.+/, '_').slice(0, 120) || '_'
  return path.join(dir, `${slug}.json`)
}

function validCopy(d) {
  return d && typeof d === 'object' && Array.isArray(d.tree) && d.files && typeof d.files === 'object' && !Array.isArray(d.files) && d.shas && typeof d.shas === 'object'
}

export function createSavedDocs({ dir = SAVED_DIR, probe, exec, seed = () => null, skip = () => false, now = Date.now }) {
  const copies = new Map() // repo -> copy, or null when there is none (so a missing or corrupt file is read once)
  const inflight = new Map()

  function readDisk(repo) {
    try {
      const d = JSON.parse(readFileSync(savedFileFor(dir, repo), 'utf8'))
      return validCopy(d) ? d : null
    } catch {
      return null // missing or corrupt: rebuilt by the next check, never re-read in a loop
    }
  }

  function fromSeed(repo) {
    let s = null
    try {
      s = seed(repo)
    } catch {
      return null
    }
    const docs = (s?.docs || []).filter((d) => isDocPath(d.path) && !d.path.endsWith('.ipynb') && typeof d.content === 'string')
    if (!docs.length) return null
    const at = Date.parse(s.at) || null
    return { v: VERSION, repo, etag: null, savedAt: at, checkedAt: null, shas: {}, tree: docTreeFromPaths(docs.map((d) => d.path)), files: Object.fromEntries(docs.map((d) => [d.path, d.content])) }
  }

  function save(repo, copy) {
    copies.set(repo, copy)
    try {
      mkdirSync(dir, { recursive: true })
      const file = savedFileFor(dir, repo)
      writeFileSync(`${file}.tmp`, JSON.stringify(copy))
      renameSync(`${file}.tmp`, file)
    } catch {
      // unwritable: the copy still serves from memory this session
    }
  }

  // The saved copy, or null. Never touches the network.
  function peek(repo) {
    if (!copies.has(repo)) copies.set(repo, readDisk(repo) || fromSeed(repo))
    return copies.get(repo)
  }

  async function check(repo) {
    if (skip()) return { status: 'skipped' }
    const copy = peek(repo)
    let res
    try {
      res = await probe(repo, copy?.etag || undefined)
    } catch (err) {
      return { status: 'offline', error: String(err?.message || err) }
    }
    const at = now()
    if (res?.status === 304 && copy) {
      save(repo, { ...copy, checkedAt: at })
      return { status: 'unchanged' }
    }
    const entries = res?.status === 200 && Array.isArray(res.body?.tree) ? res.body.tree : null
    if (!entries) return { status: 'offline', error: `GitHub answered ${res?.status ?? 'nothing'}` }

    const shaOf = new Map(entries.filter((e) => e && e.type === 'blob' && typeof e.path === 'string').map((e) => [e.path, e.sha]))
    const tree = docTreeFromPaths([...shaOf.keys()])
    const old = copy || { files: {}, shas: {}, tree: [] }
    const files = {}
    const shas = {}
    const changed = []
    let failed = false
    await Promise.all(
      flatPaths(tree).map(async (p) => {
        const sha = shaOf.get(p)
        const have = old.files[p]
        if (typeof have === 'string' && (old.shas[p] === sha || (!p.endsWith('.ipynb') && gitBlobSha(have) === sha))) {
          files[p] = have
          shas[p] = sha
          return
        }
        try {
          files[p] = await fetchFileContent(exec, repo, p)
          shas[p] = sha
          changed.push(p)
        } catch {
          failed = true // keep the old text, and the old ETag below, so the next open retries this file
          if (typeof have === 'string') files[p] = have
        }
      })
    )
    const treeChanged = JSON.stringify(tree) !== JSON.stringify(old.tree)
    const next = { v: VERSION, repo, etag: failed ? old.etag || null : res.etag || null, savedAt: changed.length || treeChanged || !copy ? at : old.savedAt, checkedAt: at, shas, tree, files }
    save(repo, next)
    // A failed download is reported as offline (the copy is not up to date), with whatever did change applied.
    if (failed) return { status: 'offline', error: 'some docs could not be downloaded', changed: changed.sort(), tree }
    return changed.length || treeChanged ? { status: 'changed', changed: changed.sort(), tree } : { status: 'unchanged' }
  }

  // One conditional request for the repo; racing callers share it.
  function revalidate(repo) {
    if (!inflight.has(repo)) inflight.set(repo, check(repo).finally(() => inflight.delete(repo)))
    return inflight.get(repo)
  }

  // A doc's saved text. A doc never seen before is fetched once and saved; a click during the first fill waits for it.
  async function content(repo, filePath) {
    if (!isDocPath(filePath)) throw new Error(`Not a doc path: ${filePath}`)
    if (inflight.has(repo)) await inflight.get(repo)
    const copy = peek(repo)
    if (typeof copy?.files?.[filePath] === 'string') return copy.files[filePath]
    const text = await fetchFileContent(exec, repo, filePath)
    const base = peek(repo) || { v: VERSION, repo, etag: null, savedAt: now(), checkedAt: null, shas: {}, tree: [], files: {} }
    save(repo, { ...base, files: { ...base.files, [filePath]: text } })
    return text
  }

  return { peek, revalidate, content }
}
