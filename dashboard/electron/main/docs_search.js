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
const EMPTY = { generated_at: null, docs: [] }

function flatten(tree) {
  return tree.flatMap((e) => (e.section ? e.items : [e]))
}

// With `saved` (docs_saved.js, #565) a rebuild goes through the Docs tab's saved copy: one conditional request per repo
// (a 304 is free and downloads nothing), and only docs whose blob sha changed are fetched. Without it, every file of
// every repo is downloaded again.
// `offline` builds from the saved copies alone: no request at all (the automatic build; #570).
export async function buildDocsIndex(execFileAsync, repos, indexPath = INDEX_PATH, { saved = null, offline = false } = {}) {
  const docs = []
  for (const repo of repos) {
    if (saved) {
      const full = repo.repo || `G-Eskayo/${repo.name}`
      if (!offline) await saved.revalidate(full)
      const copy = saved.peek(full)
      for (const f of flatten(copy?.tree || [])) {
        const text = copy.files[f.path]
        if (typeof text === 'string') docs.push({ repo: repo.id || repo.name, path: f.path, label: f.label, content: searchableText(f.path, text) })
      }
      continue
    }
    let files = []
    try {
      files = flatten(await listRepoDocTree(execFileAsync, repo.name))
    } catch {
      continue
    }
    const fetched = await Promise.all(
      files.map(async (f) => {
        try {
          return { repo: repo.id || repo.name, path: f.path, label: f.label, content: searchableText(f.path, await fetchFileContent(execFileAsync, repo.name, f.path)) }
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

// A doc's own name: its path and label, as typed ("docs/adr/0067-one-brief…", "pr-requirements") and as words
// ("docs adr 0067 one brief"), so "ADR 0067" or "life-of-a-ticket" finds the file (#609).
function nameText(doc) {
  const raw = `${doc.path || ''} ${doc.label || ''}`.toLowerCase()
  return `${raw} ${raw.replace(/[-_/.]+/g, ' ')}`
}

// Every word must appear in the same section, or (first section only) in the doc's name. A term's body count is capped
// at 3: a long section or JSON that repeats "a" or "of" hundreds of times must not bury the doc whose name or heading
// is the query (#570 capped deliverables; #609 docs too). A name hit outranks a heading hit, which outranks body text.
const BODY_CAP = 3
const HEADING_BONUS = 5
const NAME_BONUS = 8
export function searchDocs(index, query, { repo = null, limit = 50 } = {}) {
  const terms = (query || '').toLowerCase().split(/\s+/).filter(Boolean)
  if (terms.length === 0) return []
  const results = []
  for (const doc of index.docs) {
    if (repo && doc.repo !== repo) continue
    const name = nameText(doc)
    const named = new Set(terms.filter((t) => name.includes(t)))
    sectionsOf(doc).forEach((section, i) => {
      const body = section.text.toLowerCase()
      const head = section.heading.toLowerCase()
      const all = `${head}\n${body}`
      const byName = (t) => i === 0 && named.has(t)
      if (!terms.every((t) => all.includes(t) || byName(t))) return
      const score = terms.reduce((s, t) => s + Math.min(count(all, t), BODY_CAP) + (head.includes(t) ? HEADING_BONUS : 0) + (byName(t) ? NAME_BONUS : 0), 0)
      results.push({
        repo: doc.repo,
        path: doc.path,
        label: doc.label,
        heading: section.heading,
        headingIndex: section.headingIndex,
        snippet: snippetAround(section.text || section.heading, terms),
        terms,
        state: doc.state ?? null,
        kind: doc.kind ?? null,
        isDir: doc.isDir ?? false,
        score
      })
    })
  }
  return results.sort((a, b) => b.score - a.score).slice(0, limit)
}

// Keeps the index fresh without ever blocking a search on a rebuild unless
// there is nothing to search yet. `build` and `load` are injected for tests.
export function createIndexer({ build, load = loadIndex, maxAgeMs = MAX_AGE_MS, getLocal = async () => ({ repos: new Set(), docs: [] }) }) {
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

  function rebuild(fn = build) {
    if (!inflight) {
      inflight = fn()
        .then((idx) => (current = idx))
        .catch(() => current) // keep serving the old index; next search retries
        .finally(() => (inflight = null))
    }
    return inflight
  }

  return {
    reindex: rebuild,
    localChanged() {
      localDirty = true
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
        docCount: docs.filter((d) => d.kind !== 'deliverable').length,
        deliverableCount: docs.filter((d) => d.kind === 'deliverable' && !d.isDir).length
      }
    }
  }
}
