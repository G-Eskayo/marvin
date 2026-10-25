import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { listRepoDocTree, fetchFileContent, searchableText } from './docs.js'
import { splitSections } from '../../src/lib/docs_text.js'

// Full-text search over every browsable doc of every doc-first repo (the same
// files the Docs tab tree lists). The index is a plain JSON cache, rebuilt in
// the background when stale; search itself is a pure function over it.
export const INDEX_PATH = path.join(homedir(), '.claude', 'logs', 'docs-search-index.json')
export const MAX_AGE_MS = 30 * 60 * 1000
const EMPTY = { generated_at: null, docs: [], repos: {} }

export function persistIndex(index, indexPath = INDEX_PATH) {
  mkdirSync(path.dirname(indexPath), { recursive: true })
  writeFileSync(indexPath, JSON.stringify(index))
}

// Pure helpers: get docs or metadata for a specific repo from the index
export function docsForRepo(index, repoId) {
  return index.docs ? index.docs.filter((d) => d.repo === repoId) : []
}

export function fetchedAtFor(index, repoId) {
  return index.repos && index.repos[repoId] ? index.repos[repoId].fetchedAt : null
}

function flatten(tree) {
  return tree.flatMap((e) => (e.section ? e.items : [e]))
}

export async function buildDocsIndex(execFileAsync, repos, indexPath = INDEX_PATH) {
  const docs = []
  const reposMap = {}
  for (const repo of repos) {
    let files = []
    try {
      files = flatten(await listRepoDocTree(execFileAsync, repo.name))
    } catch {
      continue
    }
    const fetched = await Promise.all(
      files.map(async (f) => {
        try {
          const text = await fetchFileContent(execFileAsync, repo.name, f.path)
          const content = searchableText(f.path, text)
          const doc = { repo: repo.id || repo.name, path: f.path, label: f.label, content }
          if (content !== text) doc.raw = text
          return doc
        } catch {
          return null // one unreadable file must not sink the index
        }
      })
    )
    const repoId = repo.id || repo.name
    docs.push(...fetched.filter(Boolean))
    reposMap[repoId] = { fetchedAt: new Date().toISOString() }
  }
  const index = { generated_at: new Date().toISOString(), docs, repos: reposMap }
  persistIndex(index, indexPath)
  return index
}

export function loadIndex(indexPath = INDEX_PATH) {
  if (!existsSync(indexPath)) return EMPTY
  try {
    const data = JSON.parse(readFileSync(indexPath, 'utf-8'))
    if (!Array.isArray(data.docs)) return EMPTY
    return { ...data, repos: data.repos || {} }
  } catch {
    return EMPTY
  }
}

export function isStale(index, maxAgeMs = MAX_AGE_MS) {
  if (!index.generated_at) return true
  return Date.now() - Date.parse(index.generated_at) > maxAgeMs
}

// Fetch all docs for a single repository and return them with a timestamp
export async function refreshRepoIndex(execFileAsync, repo, indexPath = INDEX_PATH) {
  const files = flatten(await listRepoDocTree(execFileAsync, repo.name))
  const fetched = await Promise.all(
    files.map(async (f) => {
      try {
        const text = await fetchFileContent(execFileAsync, repo.name, f.path)
        const content = searchableText(f.path, text)
        const doc = { repo: repo.id || repo.name, path: f.path, label: f.label, content }
        if (content !== text) doc.raw = text
        return doc
      } catch {
        return null
      }
    })
  )
  return { docs: fetched.filter(Boolean), fetchedAt: new Date().toISOString() }
}

function snippetAround(text, terms) {
  const flat = text.replace(/\s+/g, ' ').trim()
  const lower = flat.toLowerCase()
  const at = Math.min(...terms.map((t) => lower.indexOf(t)).filter((i) => i >= 0), Infinity)
  if (at === Infinity) return flat.slice(0, 160)
  const start = Math.max(0, at - 60)
  const end = Math.min(flat.length, at + 100)
  return `${start > 0 ? '…' : ''}${flat.slice(start, end)}${end < flat.length ? '…' : ''}`
}

const count = (hay, needle) => hay.split(needle).length - 1

// A doc is split into sections once, not on every search (docs are kept in memory between searches).
const sectionCache = new WeakMap()
function sectionsOf(doc) {
  let hit = sectionCache.get(doc)
  if (!hit || hit.content !== doc.content) {
    hit = { content: doc.content, sections: splitSections(doc.content) }
    sectionCache.set(doc, hit)
  }
  return hit.sections
}

export function searchDocs(index, query, { repo = null, limit = 50 } = {}) {
  const terms = (query || '').toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return []
  const results = []
  for (const doc of index.docs) {
    if (repo && doc.repo !== repo) continue
    for (const section of sectionsOf(doc)) {
      const body = section.text.toLowerCase()
      const head = section.heading.toLowerCase()
      const label = doc.label.toLowerCase()
      const all = `${head}\n${body}`
      if (!terms.every((t) => all.includes(t))) continue
      const score = terms.reduce((s, t) => s + count(all, t) + (head.includes(t) ? 5 : 0) + (label.includes(t) ? 2 : 0), 0)
      results.push({
        repo: doc.repo,
        path: doc.path,
        label: doc.label,
        heading: section.heading,
        headingIndex: section.headingIndex,
        snippet: snippetAround(section.text || section.heading, terms),
        terms,
        state: doc.state ?? null,
        score
      })
    }
  }
  return results.sort((a, b) => b.score - a.score).slice(0, limit)
}

// Keeps the index fresh without ever blocking a search on a rebuild unless
// there is nothing to search yet. `build` and `load` are injected for tests.
export function createIndexer({ build, load = loadIndex, maxAgeMs = MAX_AGE_MS, getLocal = async () => ({ repos: new Set(), docs: [] }), persist }) {
  let current = null
  let inflight = null
  // Local clones' docs, read once and kept: re-reading every project's docs from disk on every keystroke made a search
  // take up to 20 s (2026-10-09). A docs change (localChanged) refreshes them in the background; searches meanwhile
  // use what was read last, and only the very first search waits for a read.
  let local = null
  let localDirty = false
  let localInflight = null
  function refreshLocal() {
    if (!localInflight) {
      localDirty = false
      localInflight = Promise.resolve()
        .then(() => getLocal())
        .then((l) => (local = l))
        .catch(() => local)
        .finally(() => (localInflight = null))
    }
    return localInflight
  }
  async function localDocs() {
    if (!local) return (await refreshLocal()) || { repos: new Set(), docs: [] }
    if (localDirty) refreshLocal()
    return local
  }

  function rebuild() {
    if (!inflight) {
      inflight = build()
        .then((idx) => (current = idx))
        .catch(() => current) // keep serving the old index; next search retries
        .finally(() => (inflight = null))
    }
    return inflight
  }

  // Private: update current and persist (assign current = next, fire-and-forget persist)
  function commit(next) {
    current = next
    if (persist) {
      try {
        Promise.resolve(persist(next)).catch(() => {})
      } catch {
      }
    }
  }

  return {
    reindex: rebuild,
    localChanged() {
      localDirty = true
    },
    peek() {
      return current || load()
    },
    applyRepoDocs(repoId, docs, fetchedAt) {
      if (!current) current = load()
      const next = {
        generated_at: current.generated_at || new Date().toISOString(),
        docs: [...current.docs.filter((d) => d.repo !== repoId), ...docs],
        repos: {
          ...current.repos,
          [repoId]: { fetchedAt }
        }
      }
      commit(next)
    },
    upsertDoc(doc) {
      if (!current) current = load()
      const next = {
        generated_at: current.generated_at,
        docs: [...current.docs.filter((d) => !(d.repo === doc.repo && d.path === doc.path)), doc],
        repos: current.repos
      }
      commit(next)
    },
    async search(query, opts) {
      let idx = current || load()
      if (idx.docs.length === 0) idx = (await rebuild()) || idx
      else if (isStale(idx, maxAgeMs)) rebuild()
      // Repos with a local clone are read live from disk (so uncommitted edits are
      // searchable); only the rest come from the cached GitHub index.
      const here = await localDocs()
      const docs = [...idx.docs.filter((d) => !here.repos.has(d.repo)), ...here.docs]
      return {
        results: searchDocs({ docs }, query, opts),
        indexedAt: idx.generated_at,
        indexing: inflight !== null,
        docCount: docs.length
      }
    }
  }
}
