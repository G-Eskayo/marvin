import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { listRepoDocTree, fetchFileContent } from './docs.js'
import { splitSections } from '../../src/lib/docs_text.js'

// Full-text search over every browsable doc of every doc-first repo (the same
// files the Docs tab tree lists). The index is a plain JSON cache, rebuilt in
// the background when stale; search itself is a pure function over it.
export const INDEX_PATH = path.join(homedir(), '.claude', 'logs', 'docs-search-index.json')
export const MAX_AGE_MS = 30 * 60 * 1000
const EMPTY = { generated_at: null, docs: [] }

function flatten(tree) {
  return tree.flatMap((e) => (e.section ? e.items : [e]))
}

export async function buildDocsIndex(execFileAsync, repos, indexPath = INDEX_PATH) {
  const docs = []
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
          return { repo: repo.name, path: f.path, label: f.label, content: await fetchFileContent(execFileAsync, repo.name, f.path) }
        } catch {
          return null // one unreadable file must not sink the index
        }
      })
    )
    docs.push(...fetched.filter(Boolean))
  }
  const index = { generated_at: new Date().toISOString(), docs }
  mkdirSync(path.dirname(indexPath), { recursive: true })
  writeFileSync(indexPath, JSON.stringify(index))
  return index
}

export function loadIndex(indexPath = INDEX_PATH) {
  if (!existsSync(indexPath)) return EMPTY
  try {
    const data = JSON.parse(readFileSync(indexPath, 'utf-8'))
    return Array.isArray(data.docs) ? data : EMPTY
  } catch {
    return EMPTY
  }
}

export function isStale(index, maxAgeMs = MAX_AGE_MS) {
  if (!index.generated_at) return true
  return Date.now() - Date.parse(index.generated_at) > maxAgeMs
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

export function searchDocs(index, query, { repo = null, limit = 50 } = {}) {
  const terms = (query || '').toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return []
  const results = []
  for (const doc of index.docs) {
    if (repo && doc.repo !== repo) continue
    for (const section of splitSections(doc.content)) {
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
        score
      })
    }
  }
  return results.sort((a, b) => b.score - a.score).slice(0, limit)
}

// Keeps the index fresh without ever blocking a search on a rebuild unless
// there is nothing to search yet. `build` and `load` are injected for tests.
export function createIndexer({ build, load = loadIndex, maxAgeMs = MAX_AGE_MS }) {
  let current = null
  let inflight = null

  function rebuild() {
    if (!inflight) {
      inflight = build()
        .then((idx) => (current = idx))
        .catch(() => current) // keep serving the old index; next search retries
        .finally(() => (inflight = null))
    }
    return inflight
  }

  return {
    reindex: rebuild,
    async search(query, opts) {
      let idx = current || load()
      if (idx.docs.length === 0) idx = (await rebuild()) || idx
      else if (isStale(idx, maxAgeMs)) rebuild()
      return {
        results: searchDocs(idx, query, opts),
        indexedAt: idx.generated_at,
        indexing: inflight !== null,
        docCount: idx.docs.length
      }
    }
  }
}
