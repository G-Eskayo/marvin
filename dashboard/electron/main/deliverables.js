import { readFileSync, writeFileSync, mkdirSync, renameSync, readdirSync, lstatSync } from 'fs'
import { homedir } from 'os'
import path from 'path'
import { createHash } from 'crypto'
import { outboxRoot, resolveOutboxPath, summarizeOutbox, readHead, MAX_TEXT_BYTES } from './outbox.js'
import { fileKind } from '../../src/lib/file_kinds.js'
import { varPath, migrateOnce } from './marvin_paths.js'

// Deliverables in the Docs tab (#570 "Docs: fold the Files tab into Docs", design docs/plans/docs-files-merge.md §2):
// each top-level ~/.claude/outbox item is matched to a catalog project from text, never from a hand-kept list. A port
// of the measurement the design PR ran (~/.claude/outbox/marvin-403-docs-files-merge-2026-10-21/
// outbox-match-measurement.py), tier for tier. The first tier that gives exactly one project wins:
//   1. name          a project slug appears as whole words in the item name (longest wins; a number after it = ticket)
//   1b. inside-name  the item's words are a run inside exactly one project's slug (one word only if it starts the slug)
//   2. number        pr-359 / ticket-402 / t555, when exactly one repo has that number
//   3. content       G-Eskayo/<repo> or ~/Developer/<dir>/ in the first 2 KB of up to 20 text files; one must lead 2:1
//   4. docs phrase   (top-level only) a 2-4 word window of the name, 2+ times in one project's docs and 2x any other
// Children follow their folder unless they name a different project themselves (tiers 1-3); an unmatched folder is
// split child by child; what's left is Unsorted.
//
// Complexity: matching is O((I + C) · V · L) substring checks (I items, C children, V vocabulary slugs, L name length),
// plus bounded I/O for the content tier (≤ 20 files × 2 KB per unmatched item) and O(W · T) for the docs tier.
// Results are cached by (item name, mtime): an outbox change re-matches only the changed item. Space: O(I + C) records.
export const UNSORTED_ID = '__unsorted__'
// MARVIN-owned per-machine state (self-reliance rule): ~/.agents/var, not ~/.claude. Resolved on first use.
export const matchesPath = () => varPath('outbox-matches.json')
const LEGACY_MATCHES = () => path.join(homedir(), '.claude', 'logs', 'outbox-matches.json')
const VERSION = 1

export const slug = (s) => String(s ?? '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
const DATE = /(?<![0-9])(20\d\d-\d\d-\d\d|20\d{6}(\d{4})?)(?![0-9])/g
const stemOf = (name) => (name.includes('.') && !name.startsWith('.') ? name.slice(0, name.lastIndexOf('.')) : name)

// An item name's words: the extension and dates dropped, slugged.
export function wordsOf(name) {
  return slug(stemOf(String(name)).replace(DATE, ' ')).split('-').filter(Boolean)
}

export function dateOf(name) {
  const m = String(name).match(/20\d\d-\d\d-\d\d/)
  return m ? m[0] : null
}

const STOP = new Set(['the', 'and', 'of', 'for', 'to', 'a', 'in', 'on', 'before', 'after', 'page', 'files', 'file', 'app'])
const TEXT_EXT = new Set(['.md', '.txt', '.json', '.html', '.patch', '.diff', '.py', '.yml', '.sh'])
const QUAL = /\bG-Eskayo\/([A-Za-z0-9_.-]+)/g
const reEscape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// What the tiers match against, derived from the catalog (and the docs and board data already in memory).
// projects: catalog projects; overrides: overrides.json (aliases); maxNumber: repo -> highest ticket/PR number known;
// docsText: project id -> lowercased CONTEXT + README + ADR text.
export function buildContext({ projects = [], overrides = {}, maxNumber = {}, docsText = {}, home = homedir() }) {
  const vocab = new Map()
  const add = (v, id) => {
    if (v.length >= 3 && v !== 'agents') vocab.set(v, new Set([...(vocab.get(v) || []), id]))
  }
  const repoToId = {}
  const local = {}
  const status = {}
  const names = {}
  for (const p of projects) {
    status[p.id] = p.status
    names[p.id] = p.name
    const cands = new Set([String(p.id).split(':').pop(), slug(p.name)])
    if (p.repo) {
      cands.add(slug(p.repo.split('/')[1]))
      repoToId[p.repo] = p.id
    }
    for (const lp of p.localPaths || []) {
      cands.add(slug(path.basename(lp)))
      if (lp.endsWith('/.agents')) continue // every MARVIN run command mentions ~/.agents/venv: it proves nothing
      local[lp] = p.id
      local[lp.replace(home, '~')] = p.id
    }
    for (const a of overrides?.[p.id]?.aliases || []) cands.add(slug(a))
    for (const c of cands) add(c, p.id)
  }
  return { vocab, repoToId, local, status, names, maxNumber, docsText }
}

function tName(ctx, ws) {
  const s = `-${ws.join('-')}-`
  const best = []
  for (const [v, ids] of ctx.vocab) if (s.includes(`-${v}-`)) best.push({ len: v.length, v, ids })
  if (!best.length) return null
  best.sort((a, b) => b.len - a.len || (a.v < b.v ? 1 : a.v > b.v ? -1 : 0))
  const top = best[0]
  const same = (a, b) => a.size === b.size && [...a].every((x) => b.has(x))
  if (top.ids.size !== 1 || best.slice(1).some((b) => b.len === top.len && !same(b.ids, top.ids))) return null
  const id = [...top.ids][0]
  const m = s.match(new RegExp(`-${reEscape(top.v)}-(\\d{1,6})-`))
  return { id, how: 'name', reason: `name '${top.v}'`, ticket: m ? Number(m[1]) : null }
}

function pick(ctx, ids) {
  if (ids.size === 1) return [...ids][0]
  const live = [...ids].filter((i) => ctx.status[i] === 'active' || ctx.status[i] === 'recent')
  return live.length === 1 ? live[0] : null
}

function tInside(ctx, words) {
  const ws = words.filter((w) => !/^\d+$/.test(w))
  if (!ws.length) return null
  const run = `-${ws.join('-')}-`
  const ids = new Set()
  for (const [v, set] of ctx.vocab) {
    const hit = ws.length === 1 ? `-${v}-`.startsWith(run) && ws[0].length >= 4 : `-${v}-`.includes(run)
    if (hit) set.forEach((i) => ids.add(i))
  }
  const id = ids.size ? pick(ctx, ids) : null
  return id ? { id, how: 'inside-name', reason: `'${ws.join('-')}' is part of its name`, ticket: null } : null
}

function tNumber(ctx, ws) {
  const m = ws.join('-').match(/(?:^|-)(pr|ticket|t)-?(\d{1,6})(?:-|$)/)
  if (!m) return null
  const n = Number(m[2])
  const hits = Object.entries(ctx.maxNumber).filter(([, max]) => n >= 1 && n <= max).map(([r]) => r)
  if (hits.length !== 1 || !ctx.repoToId[hits[0]]) return null
  return { id: ctx.repoToId[hits[0]], how: 'number', reason: `#${n} exists only in ${hits[0]}`, ticket: n }
}

// Up to 20 text files of an item (itself, or the first 20 by path inside it), bounded walk.
function textFilesOf(relPath) {
  let st
  try {
    st = lstatSync(resolveOutboxPath(relPath))
  } catch {
    return []
  }
  if (st.isFile()) return [relPath]
  if (!st.isDirectory()) return []
  const all = []
  const stack = [relPath]
  while (stack.length && all.length < 2000) {
    const dir = stack.pop()
    let entries
    try {
      entries = readdirSync(path.join(outboxRoot(), dir), { withFileTypes: true })
    } catch {
      continue
    }
    for (const e of entries) {
      const p = `${dir}/${e.name}`
      if (e.isDirectory()) stack.push(p)
      else if (e.isFile()) all.push(p)
    }
  }
  return all.sort().slice(0, 20)
}

function tContent(ctx, relPath) {
  const votes = {}
  for (const f of textFilesOf(relPath)) {
    if (!TEXT_EXT.has(path.extname(f).toLowerCase())) continue
    let head
    try {
      head = readHead(path.join(outboxRoot(), f), 2048)
    } catch {
      continue
    }
    for (const [lp, id] of Object.entries(ctx.local)) if (head.includes(`${lp}/`)) votes[id] = (votes[id] || 0) + 1
    for (const m of head.matchAll(QUAL)) {
      const id = ctx.repoToId[`G-Eskayo/${m[1].replace(/\.+$/, '')}`]
      if (id) votes[id] = (votes[id] || 0) + 1
    }
  }
  const top = Object.entries(votes).sort((a, b) => b[1] - a[1])
  if (!top.length) return null
  if (top.length === 1 || top[0][1] > 2 * top[1][1]) {
    const repo = Object.entries(ctx.repoToId).find(([, id]) => id === top[0][0])?.[0]
    return { id: top[0][0], how: 'content', reason: `${repo || ctx.names[top[0][0]]} named in its files`, ticket: null }
  }
  return null
}

function tDocs(ctx, words) {
  const ws = words.filter((w) => !/^\d+$/.test(w))
  const entries = Object.entries(ctx.docsText)
  for (let size = Math.min(ws.length, 4); size > 1; size--) {
    for (let i = 0; i + size <= ws.length; i++) {
      const win = ws.slice(i, i + size)
      if (STOP.has(win[0]) || STOP.has(win[win.length - 1])) continue
      const re = new RegExp(`\\b${win.map(reEscape).join('[\\s_-]+')}\\b`, 'g')
      const c = entries.map(([id, t]) => [(t.match(re) || []).length, id]).sort((a, b) => b[0] - a[0] || (a[1] < b[1] ? 1 : -1))
      const [first = [0], second = [0]] = c
      if (first[0] >= 2 && first[0] >= 2 * second[0]) return { id: first[1], how: 'docs', reason: `phrase '${win.join(' ')}' in its docs`, ticket: null }
    }
  }
  return null
}

export function matchName(ctx, relPath, { top = true } = {}) {
  const ws = wordsOf(path.basename(relPath))
  const r = tName(ctx, ws) || tInside(ctx, ws) || tNumber(ctx, ws) || tContent(ctx, relPath)
  if (r || !top) return r
  return tDocs(ctx, ws)
}

// A number in a top-level name is that project's ticket when the project's repo has it (seal-speak-share-139 -> #139).
function ticketOf(ctx, name, m) {
  if (m.ticket) return m.ticket
  const repo = Object.entries(ctx.repoToId).find(([, id]) => id === m.id)?.[0]
  const max = repo ? ctx.maxNumber[repo] : 0
  const n = wordsOf(name).map(Number).find((x) => Number.isInteger(x) && x >= 1 && x <= max)
  return n || null
}

const ctxKey = (ctx) =>
  createHash('sha1')
    .update(JSON.stringify([[...ctx.vocab].map(([v, s]) => [v, [...s].sort()]).sort(), ctx.maxNumber, Object.entries(ctx.docsText).map(([k, t]) => [k, t.length]).sort(), ctx.status]))
    .digest('hex')

// One top-level item matched, with its children's overrides (the measurement script's main loop).
function matchItem(ctx, name, isDir) {
  const m = matchName(ctx, name)
  const kids = []
  if (isDir) {
    let entries = []
    try {
      entries = readdirSync(path.join(outboxRoot(), name), { withFileTypes: true }).filter((e) => !e.name.startsWith('.')).map((e) => e.name).sort()
    } catch {
      entries = []
    }
    for (const k of entries) {
      const km = matchName(ctx, `${name}/${k}`, { top: false })
      if (!m || (km && km.id !== m.id)) kids.push({ name: k, match: km })
    }
  }
  return { match: m ? { ...m, ticket: ticketOf(ctx, name, m) } : null, kids }
}

function topItems() {
  let entries
  try {
    entries = readdirSync(outboxRoot(), { withFileTypes: true })
  } catch {
    return []
  }
  return entries
    .filter((e) => !e.name.startsWith('.') && e.name !== 'README.md' && (e.isDirectory() || e.isFile()))
    .map((e) => {
      let mtimeMs = 0
      try {
        mtimeMs = lstatSync(path.join(outboxRoot(), e.name)).mtimeMs
      } catch {
        // vanished between listing and stat: matched as it was named
      }
      return { name: e.name, isDir: e.isDirectory(), mtimeMs }
    })
    .sort((a, b) => a.name.localeCompare(b.name))
}

// A deliverable as the tree, the grid and search show it.
function entryFor(rel, summary, m) {
  const name = path.basename(rel)
  return {
    path: rel,
    name: rel,
    isDir: !!summary?.isDir,
    count: summary?.count ?? 0,
    size: summary?.size ?? null,
    date: dateOf(name) || (summary?.mtimeMs ? new Date(summary.mtimeMs).toISOString().slice(0, 10) : null),
    covers: summary?.covers || [],
    kinds: summary?.kinds || [],
    how: m?.how || null,
    reason: m?.reason || null,
    ticket: m?.ticket || null
  }
}

const newestFirst = (a, b) => (b.date || '').localeCompare(a.date || '') || a.name.localeCompare(b.name)

// The cached match map. view() answers from memory (or the saved file) at once; refresh(names) re-matches only the
// named top-level items, or every item whose (name, mtime) changed, and everything when the context changed.
// `pdfText` (pdf_text.js, #611): the cached text of a PDF by absolute path, or null; PDFs stay name-only without it.
export function createDeliverables({ getContext, cachePath = null, pdfText = null }) {
  let resolved = cachePath
  const file = () => {
    if (!resolved) {
      resolved = matchesPath()
      migrateOnce(LEGACY_MATCHES(), resolved)
    }
    return resolved
  }
  let state = null // { key, items: { name: { mtimeMs, isDir, match, kids, summary, kidSummaries } } }

  function load() {
    if (state) return state
    try {
      const d = JSON.parse(readFileSync(file(), 'utf8'))
      if (d?.v === VERSION && d.items && typeof d.items === 'object') state = d
    } catch {
      state = null // missing or corrupt: rebuilt once below
    }
    return state
  }

  function save() {
    try {
      mkdirSync(path.dirname(file()), { recursive: true })
      writeFileSync(`${file()}.tmp`, JSON.stringify(state))
      renameSync(`${file()}.tmp`, file())
    } catch {
      // unwritable: memory still serves this session
    }
  }

  function refresh(changed = null) {
    // Board numbers come from memory (github_state); until the boards load this session, the last saved ones are used.
    const input = getContext()
    const saved = load()
    const maxNumber = { ...(saved?.maxNumber || {}), ...(input.maxNumber || {}) }
    const ctx = buildContext({ ...input, maxNumber })
    const key = ctxKey(ctx)
    const prev = saved
    const all = prev && prev.key === key
    const items = {}
    const dirty = changed ? new Set(changed.map((n) => String(n).split('/')[0])) : null
    for (const it of topItems()) {
      const old = prev?.items?.[it.name]
      const keep = all && old && old.mtimeMs === it.mtimeMs && old.isDir === it.isDir && !(dirty && dirty.has(it.name))
      if (keep) {
        items[it.name] = old
        continue
      }
      const { match, kids } = matchItem(ctx, it.name, it.isDir)
      const summary = summarizeOutbox(it.name)
      const kidSummaries = Object.fromEntries(kids.map((k) => [k.name, summarizeOutbox(`${it.name}/${k.name}`)]))
      items[it.name] = { mtimeMs: it.mtimeMs, isDir: it.isDir, match, kids, summary, kidSummaries }
    }
    state = { v: VERSION, key, at: Date.now(), maxNumber, items }
    save()
    return view()
  }

  // Where one top-level item's pieces go: [{ repo, entry, leftoverOf? }].
  function placed(name, it) {
    if (it.match) {
      return [
        { repo: it.match.id, entry: entryFor(name, it.summary, it.match) },
        ...it.kids.filter((k) => k.match).map((k) => ({ repo: k.match.id, entry: entryFor(`${name}/${k.name}`, it.kidSummaries?.[k.name], k.match) }))
      ]
    }
    const matchedKids = it.kids.filter((k) => k.match)
    if (!matchedKids.length) return [{ repo: UNSORTED_ID, entry: entryFor(name, it.summary, null) }]
    return [
      ...matchedKids.map((k) => ({ repo: k.match.id, entry: entryFor(`${name}/${k.name}`, it.kidSummaries?.[k.name], k.match) })),
      ...it.kids.filter((k) => !k.match).map((k) => ({ repo: UNSORTED_ID, entry: entryFor(`${name}/${k.name}`, it.kidSummaries?.[k.name], null), leftoverOf: name }))
    ]
  }

  // { byProject: { id: [entry] }, unsorted: { whole: [entry], leftovers: [{ parent, entries }] }, count, at }
  let viewCache = null // { s, v }: the view is rebuilt only when the match map changes, not on every tree() call
  function view() {
    if (!load()) refresh()
    const s = state
    if (viewCache?.s === s) return viewCache.v
    const byProject = {}
    const whole = []
    const left = new Map()
    for (const [name, it] of Object.entries(s.items)) {
      for (const { repo, entry, leftoverOf } of placed(name, it)) {
        if (leftoverOf) left.set(leftoverOf, [...(left.get(leftoverOf) || []), entry])
        else if (repo === UNSORTED_ID) whole.push(entry)
        else (byProject[repo] = byProject[repo] || []).push(entry)
      }
    }
    for (const list of Object.values(byProject)) list.sort(newestFirst)
    whole.sort(newestFirst)
    const leftovers = [...left].map(([parent, entries]) => ({ parent, entries }))
    const count = whole.length + leftovers.reduce((n, l) => n + l.entries.length, 0)
    const v = { byProject, unsorted: { whole, leftovers }, count, at: s.at }
    viewCache = { s, v }
    return v
  }

  // Search entries, cached per top-level item: an outbox change re-reads only the item that changed.
  let docsCache = new WeakMap()
  const readText = (rel) => readSmallText(rel, pdfText)
  function searchDocs(opts) {
    if (!load()) refresh()
    const s = state
    const out = []
    for (const [name, it] of Object.entries(s.items)) {
      let d = docsCache.get(it)
      if (!d) docsCache.set(it, (d = deliverableDocs(placed(name, it), { readText, ...opts })))
      out.push(...d)
    }
    return out
  }

  // New PDF text arrived (pdf_text.js onReady): the next search re-reads each item's text once.
  function invalidateSearch() {
    docsCache = new WeakMap()
  }

  return { view, refresh, searchDocs, invalidateSearch }
}

// What the docs search indexes for deliverables (design §3): one section of path words for every file (so images,
// PDFs and video are found by name), plus the text of text files under 200 KB. Past 200 files in one item, paths only.
// Entries take the shape searchDocs already reads, with kind: 'deliverable'.
const TEXT_KINDS = new Set(['markdown', 'text', 'json', 'table', 'html']) // design §3: md, txt, json, csv, html (code and diffs by name only)
const MAX_INDEX_TEXT = 200 * 1024
export function deliverableDocs(placedItems, { listFiles = filesUnder, readText = readSmallText } = {}) {
  const docs = []
  // The path words are the entry's first heading, so a hit on a file or folder name ranks like a heading hit (a long
  // JSON that merely contains the words doesn't bury it).
  const words = (rel) => `# ${wordsOf(rel.replace(/\//g, '-')).join(' ')}`
  for (const { repo, entry: e } of placedItems) {
    docs.push({ repo, path: `outbox/${e.path}${e.isDir ? '/' : ''}`, label: path.basename(e.path), content: words(e.path), kind: 'deliverable', isDir: e.isDir })
    const files = e.isDir ? listFiles(e.path) : []
    if (!e.isDir) {
      const text = readText(e.path)
      if (text) docs.push({ repo, path: `outbox/${e.path}`, label: path.basename(e.path), content: `${words(e.path)}\n\n${text}`, kind: 'deliverable' })
      continue
    }
    const withText = files.length <= 200
    for (const f of files) {
      const text = withText ? readText(f) : null
      docs.push({ repo, path: `outbox/${f}`, label: path.basename(f), content: text ? `${words(f)}\n\n${text}` : words(f), kind: 'deliverable' })
    }
  }
  return docs
}

function filesUnder(rel, limit = 2000) {
  const out = []
  const stack = [rel]
  while (stack.length && out.length < limit) {
    const dir = stack.pop()
    let entries
    try {
      entries = readdirSync(path.join(outboxRoot(), dir), { withFileTypes: true })
    } catch {
      continue
    }
    for (const e of entries) {
      if (e.name.startsWith('.')) continue
      if (e.isDirectory()) stack.push(`${dir}/${e.name}`)
      else if (e.isFile()) out.push(`${dir}/${e.name}`)
    }
  }
  return out.sort()
}

function readSmallText(rel, pdfText = null) {
  if (fileKind(rel).kind === 'pdf') {
    if (!pdfText) return null
    try {
      return pdfText.peek(resolveOutboxPath(rel)) // cached text, or null while the background pass reads it
    } catch {
      return null
    }
  }
  if (!TEXT_KINDS.has(fileKind(rel).kind)) return null
  try {
    const full = resolveOutboxPath(rel)
    const st = lstatSync(full)
    if (!st.isFile() || st.size > Math.min(MAX_INDEX_TEXT, MAX_TEXT_BYTES)) return null
    const buf = readFileSync(full)
    if (buf.includes(0)) return null
    const text = buf.toString('utf8')
    return fileKind(rel).kind === 'html' ? text.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, ' ').replace(/<[^>]+>/g, ' ') : text
  } catch {
    return null
  }
}
